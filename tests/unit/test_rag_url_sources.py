"""
Unit tests for URL sources: the SSRF-guarded web fetch, the shallow clone,
and the chunk records they produce (docs/design-rag.md §5.1–§5.3, §7.1, §9.4).

No Docker stack and no network required: DNS, HTTP and git are faked, except
one test that runs the local git to check that non-https transports are off.

Run with:
    cd tests/unit && pytest test_rag_url_sources.py -v
"""

from __future__ import annotations

import base64
import os
import pathlib
import shutil

import httpx
import pytest
from app.services.rag import ingestion
from app.services.rag.sources import fetch, repo
from app.services.resource_service import PRESETS

SAMPLE = pathlib.Path(__file__).parents[2] / "eval" / "sample_data"
SYNC_ID = "f" * 32
PUBLIC_IP = "93.184.215.14"
REPO_URL = "https://git.doit.wisc.edu/group/course.git"
SHA = "0123456789abcdef0123456789abcdef01234567"


def profile(name: str = "sliding-window") -> ingestion.ProfileSnapshot:
    preset = next(p for p in PRESETS if p["name"] == name)
    return ingestion.ProfileSnapshot(
        name, preset["embedding_model"], preset["chunking"], f"qna_c1__{name}"
    )


def url_resource(rid: int, rtype: str, url: str, ref: str | None = None):
    names = {"REPOSITORY": "Course repository", "SYLLABUS": "Syllabus"}
    return ingestion.ResourceSnapshot(
        rid, 1, rtype, "URL", names[rtype], url, None, ref
    )


async def fake_embed(texts):
    return [[float(len(t) % 7), 1.0, float("Slip" in t)] for t in texts]


# --- the SSRF guard ----------------------------------------------------------


@pytest.mark.parametrize(
    "ip, allowed",
    [
        (PUBLIC_IP, True),
        ("2606:4700::6810:84e5", True),
        ("127.0.0.1", False),
        ("10.0.0.5", False),
        ("172.18.0.7", False),  # a compose service on the Docker network
        ("192.168.1.1", False),
        ("169.254.169.254", False),  # the cloud metadata server
        ("100.64.0.1", False),
        ("0.0.0.0", False),
        ("224.0.0.1", False),
        ("::1", False),
        ("fe80::1", False),
        ("fd00::1", False),
        ("::ffff:127.0.0.1", False),  # IPv4-mapped loopback
    ],
)
def test_only_public_addresses_are_allowed(ip, allowed):
    assert fetch.address_allowed(ip) is allowed


@pytest.fixture
def dns(monkeypatch):
    """host -> addresses; every lookup is recorded."""
    table: dict[str, list[str]] = {}
    lookups: list[str] = []

    async def resolve(host, port):
        lookups.append(host)
        return table[host]

    monkeypatch.setattr(fetch, "resolve", resolve)
    table["lookups"] = lookups  # type: ignore[assignment]
    return table


@pytest.mark.parametrize(
    "host", ["ollama", "infinity", "chromadb", "mysql", "redis", "backend"]
)
async def test_internal_service_names_are_rejected(dns, host):
    with pytest.raises(fetch.FetchError, match="address not allowed"):
        await fetch.checked_ip(host, 80)
    assert dns["lookups"] == []


async def test_a_host_with_any_private_address_is_rejected(dns):
    dns["mixed.example"] = [PUBLIC_IP, "10.1.2.3"]
    with pytest.raises(fetch.FetchError, match="address not allowed"):
        await fetch.checked_ip("mixed.example", 443)


@pytest.mark.parametrize(
    "url, message",
    [
        ("ftp://example.com/x", "only http and https"),
        ("file:///etc/passwd", "only http and https"),
        ("https://user:pw@example.com/", "username or password"),
    ],
)
async def test_bad_urls_are_refused_before_any_lookup(dns, url, message):
    with pytest.raises(fetch.FetchError, match=message):
        await fetch.fetch_page(url)
    assert dns["lookups"] == []


def transport(routes: dict[str, httpx.Response], seen: list[httpx.Request]):
    """Responds by the request's Host header and path; records every request."""

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return routes[f"{request.headers['host']}{request.url.path}"]

    return httpx.MockTransport(handler)


async def test_connects_to_the_checked_ip_with_the_real_host_and_sni(dns):
    dns["syllabus.example"] = [PUBLIC_IP]
    seen: list[httpx.Request] = []
    routes = {"syllabus.example/p": httpx.Response(200, content=b"<h1>Syllabus</h1>")}
    page = await fetch.fetch_page(
        "https://syllabus.example/p#top", transport=transport(routes, seen)
    )
    assert page.content == b"<h1>Syllabus</h1>"
    assert page.url == "https://syllabus.example/p"
    (request,) = seen
    assert request.url.host == PUBLIC_IP
    assert request.headers["host"] == "syllabus.example"
    assert request.extensions["sni_hostname"] == "syllabus.example"


async def test_each_redirect_hop_is_checked(dns):
    dns["a.example"] = [PUBLIC_IP]
    dns["evil.example"] = ["127.0.0.1"]
    seen: list[httpx.Request] = []
    routes = {
        "a.example/": httpx.Response(
            302, headers={"location": "http://evil.example/admin"}
        )
    }
    with pytest.raises(fetch.FetchError, match="address not allowed"):
        await fetch.fetch_page("http://a.example/", transport=transport(routes, seen))
    assert len(seen) == 1  # the private host is never contacted


async def test_relative_redirects_resolve_against_the_real_host(dns):
    dns["a.example"] = [PUBLIC_IP]
    seen: list[httpx.Request] = []
    routes = {
        "a.example/old": httpx.Response(301, headers={"location": "/new"}),
        "a.example/new": httpx.Response(200, content=b"ok"),
    }
    page = await fetch.fetch_page(
        "https://a.example/old", transport=transport(routes, seen)
    )
    assert page.url == "https://a.example/new"
    assert [r.headers["host"] for r in seen] == ["a.example", "a.example"]


async def test_more_than_five_redirects_fail(dns):
    dns["loop.example"] = [PUBLIC_IP]
    routes = {"loop.example/": httpx.Response(302, headers={"location": "/"})}
    seen: list[httpx.Request] = []
    with pytest.raises(fetch.FetchError, match="more than 5 redirects"):
        await fetch.fetch_page(
            "http://loop.example/", transport=transport(routes, seen)
        )
    assert len(seen) == 6


async def test_non_200_and_oversized_pages_fail(dns, monkeypatch):
    dns["a.example"] = [PUBLIC_IP]
    routes = {
        "a.example/gone": httpx.Response(404),
        "a.example/big": httpx.Response(200, content=b"x" * 2048),
    }
    with pytest.raises(fetch.FetchError, match="HTTP 404"):
        await fetch.fetch_page("http://a.example/gone", transport=transport(routes, []))
    monkeypatch.setattr(fetch, "MAX_BYTES", 1024)
    with pytest.raises(fetch.FetchError, match="over 5 MB"):
        await fetch.fetch_page("http://a.example/big", transport=transport(routes, []))


# --- the shallow clone ---------------------------------------------------------


def test_the_token_goes_only_into_host_scoped_env_config():
    env = repo.git_env(REPO_URL, "glpat-SECRET")
    basic = base64.b64encode(b"oauth2:glpat-SECRET").decode()
    config = {
        env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"]
        for i in range(int(env["GIT_CONFIG_COUNT"]))
    }
    assert config == {
        "http.followRedirects": "false",
        "http.https://git.doit.wisc.edu/.extraHeader": f"Authorization: Basic {basic}",
    }
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert "glpat-SECRET" not in " ".join(
        repo.clone_command(REPO_URL, "main", "/tmp/x")
    )


def test_without_a_token_no_header_is_configured():
    env = repo.git_env(REPO_URL, "")
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert not any("extraHeader" in v for v in env.values())


def test_clone_command_is_shallow_hardened_and_option_safe():
    cmd = repo.clone_command(REPO_URL, "release/fa26", "/tmp/dest")
    assert cmd[:5] == [
        "git",
        "-c",
        "protocol.allow=never",
        "-c",
        "protocol.https.allow=always",
    ]
    assert ["--depth", "1"] == cmd[cmd.index("--depth") : cmd.index("--depth") + 2]
    assert "--branch=release/fa26" in cmd
    assert cmd[-3:] == ["--", REPO_URL, "/tmp/dest"]
    assert "--branch" not in repo.clone_command(REPO_URL, None, "/tmp/dest")


@pytest.mark.skipif(shutil.which("git") is None, reason="git isn't installed")
async def test_non_https_transports_are_refused(tmp_path):
    """A real repository, so the only reason the clone can fail is the transport."""
    import subprocess

    source = tmp_path / "src"
    env = {**repo.git_env(REPO_URL, ""), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}  # fmt: skip
    for args in (
        ["init", "-q", str(source)],
        ["-C", str(source), "commit", "-q", "--allow-empty", "-m", "x"],
    ):
        subprocess.run(["git", *args], env=env, check=True)
    cmd = repo.clone_command(f"file://{source}", None, str(tmp_path / "dest"))
    with pytest.raises(repo.CloneError, match="transport 'file' not allowed"):
        await repo.run_git(cmd, env, 30)
    # Without the hardening flags the same clone works, so the flags are what refused it.
    await repo.run_git(
        ["git", "clone", "-q", "--", f"file://{source}", str(tmp_path / "ok")], env, 30
    )


async def test_git_is_killed_at_the_timeout():
    with pytest.raises(repo.CloneError, match="didn't finish within"):
        await repo.run_git(["sleep", "5"], {"PATH": os.environ["PATH"]}, 0.2)


async def test_git_errors_carry_its_output():
    cmd = ["sh", "-c", "echo 'fatal: repository not found' >&2; exit 128"]
    with pytest.raises(repo.CloneError, match="fatal: repository not found"):
        await repo.run_git(cmd, {"PATH": os.environ["PATH"]}, 5)


def write(root: pathlib.Path, path: str, data: bytes = b"# x\n") -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def test_collect_files_keeps_md_and_pdf_outside_dot_paths(tmp_path):
    for path in [
        "README.md", "docs/guide.md", "slides/week1.pdf", "notes.txt",
        ".git/HEAD.md", ".github/ci.md", "docs/.draft.md", "img/logo.png",
    ]:  # fmt: skip
        write(tmp_path, path)
    (tmp_path / "link.md").symlink_to(tmp_path / "README.md")
    files, skipped = repo.collect_files(tmp_path)
    assert [p for p, _ in files] == ["README.md", "docs/guide.md", "slides/week1.pdf"]
    assert skipped == []


def test_collect_files_skips_big_files_and_enforces_the_caps(tmp_path, monkeypatch):
    write(tmp_path, "a.md", b"x" * 10)
    write(tmp_path, "b.md", b"x" * 100)
    monkeypatch.setattr(repo, "MAX_FILE_BYTES", 50)
    files, skipped = repo.collect_files(tmp_path)
    assert [p for p, _ in files] == ["a.md"]
    assert skipped == [{"path": "b.md", "reason": "over 25 MB"}]

    monkeypatch.setattr(repo, "MAX_FILE_BYTES", 1000)
    monkeypatch.setattr(repo, "MAX_FILES", 1)
    with pytest.raises(repo.CloneError, match="more than 1"):
        repo.collect_files(tmp_path)
    monkeypatch.setattr(repo, "MAX_FILES", 10)
    monkeypatch.setattr(repo, "MAX_TOTAL_BYTES", 50)
    with pytest.raises(repo.CloneError, match="over 100 MB"):
        repo.collect_files(tmp_path)


# --- records for URL resources (§5.1–§5.3) ------------------------------------


async def test_a_fetched_page_cites_the_live_page_with_a_text_fragment(monkeypatch):
    page_url = "https://pages.example/cs/syllabus"

    async def fake_fetch(url):
        assert url == "https://pages.example/syllabus"
        return fetch.FetchedPage(
            page_url, (SAMPLE / "web" / "syllabus.html").read_bytes()
        )

    monkeypatch.setattr(fetch, "fetch_page", fake_fetch)
    res = url_resource(5, "SYLLABUS", "https://pages.example/syllabus")
    out = await ingestion.extract(res, profile(), SYNC_ID, fake_embed)
    assert out.records and out.commit_sha is None
    for r in out.records:
        meta = r.metadata
        assert meta["source_url"] == meta["source_path"] == page_url
        assert meta["citation_url"].startswith(f"{page_url}#:~:text=")
        assert "\n" not in meta["citation_url"]
        assert meta["resource_type"] == "syllabus"


async def test_a_blocked_page_fails_the_run_with_the_reason(monkeypatch):
    async def blocked(url):
        raise fetch.FetchError("address not allowed")

    monkeypatch.setattr(fetch, "fetch_page", blocked)
    res = url_resource(5, "SYLLABUS", "http://10.0.0.1/")
    with pytest.raises(ingestion.IngestionError, match="address not allowed"):
        await ingestion.extract(res, profile(), SYNC_ID, fake_embed)


@pytest.fixture
def cloned(monkeypatch):
    """clone_files returns the sample repository, plus one skipped file."""
    calls = []

    async def fake_clone(url, ref):
        calls.append((url, ref))
        files = sorted(
            (p.relative_to(SAMPLE / "repo").as_posix(), p.read_bytes())
            for p in (SAMPLE / "repo").rglob("*")
            if p.is_file()
            and p.suffix in {".md", ".pdf"}
            and not p.name.startswith(".")
        )
        files.append(("broken/latin1.md", b"caf\xe9"))
        return repo.ClonedFiles(
            SHA, files, [{"path": "huge.pdf", "reason": "over 25 MB"}]
        )

    monkeypatch.setattr(repo, "clone_files", fake_clone)
    return calls


async def test_a_cloned_repository_cites_gitlab_at_the_commit(cloned):
    res = url_resource(6, "REPOSITORY", REPO_URL, "main")
    out = await ingestion.extract(res, profile(), SYNC_ID, fake_embed)
    assert cloned == [(REPO_URL, "main")]
    assert out.commit_sha == SHA
    web = "https://git.doit.wisc.edu/group/course"
    md = [
        r.metadata
        for r in out.records
        if r.metadata["resource_type"] == "repo_markdown"
    ]
    pdfs = [
        r.metadata for r in out.records if r.metadata["resource_type"] == "repo_pdf"
    ]
    assert md and pdfs
    for meta in md:
        path = meta["source_path"]
        assert meta["rel_path"] == path and not path.startswith("eval/")
        assert meta["source_url"] == f"{web}/-/blob/{SHA}/{path}"
        assert meta["citation_url"] == (
            f"{meta['source_url']}?plain=1#L{meta['line_start']}-{meta['line_end']}"
        )
    for meta in pdfs:
        assert (
            meta["citation_url"]
            == f"{web}/-/raw/{SHA}/{meta['source_path']}#page={meta['page']}"
        )
    assert {"path": "huge.pdf", "reason": "over 25 MB"} in out.skipped
    assert {"path": "broken/latin1.md", "reason": "not valid UTF-8"} in out.skipped


async def test_a_clone_failure_fails_the_run_with_the_reason(monkeypatch):
    async def failing(url, ref):
        raise repo.CloneError("git clone failed: fatal: Authentication failed")

    monkeypatch.setattr(repo, "clone_files", failing)
    res = url_resource(6, "REPOSITORY", REPO_URL)
    with pytest.raises(ingestion.IngestionError, match="Authentication failed"):
        await ingestion.extract(res, profile(), SYNC_ID, fake_embed)
