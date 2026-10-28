"""
Shallow-cloning a course repository by URL (docs/design-rag.md §7.1, §9.4).

`git clone --depth 1` runs as a subprocess with a timeout. The GitLab token
reaches git only through environment-variable config scoped to the
repository's (allowlisted) host, never on the command line or in the URL,
so it stays out of `ps`, `.git/config` and git's own messages. Redirects
and every protocol but https are off, so git only ever talks to the host
in the registered URL.
"""

from __future__ import annotations

import asyncio
import base64
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from ....config import settings
from .uploads import (
    MAX_UNCOMPRESSED_BYTES,
    MAX_UPLOAD_BYTES,
    MAX_ZIP_ENTRIES,
    REPO_EXTENSIONS,
)

# Clones get the zip caps after checkout (§7.1).
MAX_FILES = MAX_ZIP_ENTRIES
MAX_TOTAL_BYTES = MAX_UNCOMPRESSED_BYTES
MAX_FILE_BYTES = MAX_UPLOAD_BYTES
_GIT_OUTPUT_CHARS = 500


class CloneError(Exception):
    """A clone failure whose message is safe to show staff (once scrubbed)."""


@dataclass
class ClonedFiles:
    commit_sha: str
    files: list[tuple[str, bytes]] = field(default_factory=list)  # (repo path, bytes)
    skipped: list[dict] = field(default_factory=list)


def git_env(url: str, token: str) -> dict[str, str]:
    """
    The environment for git: no prompts, no user or system config, redirects
    off, and the token (if any) as a Basic auth header for this host only.
    """
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": tempfile.gettempdir(),
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.followRedirects",
        "GIT_CONFIG_VALUE_0": "false",
    }
    if token:
        host = urlsplit(url).hostname
        basic = base64.b64encode(f"oauth2:{token}".encode()).decode()
        env.update(
            {
                "GIT_CONFIG_COUNT": "2",
                "GIT_CONFIG_KEY_1": f"http.https://{host}/.extraHeader",
                "GIT_CONFIG_VALUE_1": f"Authorization: Basic {basic}",
            }
        )
    return env


def clone_command(url: str, repo_ref: str | None, dest: str) -> list[str]:
    """`repo_ref` is validated at registration; `--branch=` and `--` keep it and the URL from being options."""
    cmd = [
        "git",
        "-c", "protocol.allow=never",
        "-c", "protocol.https.allow=always",
        "clone", "--depth", "1", "--quiet",
    ]  # fmt: skip
    if repo_ref:
        cmd.append(f"--branch={repo_ref}")
    return cmd + ["--", url, dest]


async def run_git(cmd: list[str], env: dict[str, str], timeout_s: float) -> str:
    """Run git; its stdout, or CloneError with the end of its output. Killed at the timeout."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise CloneError(f"git didn't finish within {timeout_s:.0f} s")
    if proc.returncode != 0:
        message = (
            err.decode(errors="replace").strip() or f"exit status {proc.returncode}"
        )
        raise CloneError(f"git clone failed: {message[-_GIT_OUTPUT_CHARS:]}")
    return out.decode(errors="replace").strip()


def collect_files(root: Path) -> tuple[list[tuple[str, bytes]], list[dict]]:
    """
    Every `.md` and `.pdf` under `root`, skipping `.git/` and dot-paths. A file
    over 25 MB is skipped; more than 1000 files or 100 MB in total fails (§7.1).
    """
    files: list[tuple[str, bytes]] = []
    skipped: list[dict] = []
    total = 0
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if (
            path.is_symlink()
            or not path.is_file()
            or path.suffix.lower() not in REPO_EXTENSIONS
        ):
            continue
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            skipped.append({"path": rel.as_posix(), "reason": "over 25 MB"})
            continue
        total += size
        if len(files) + 1 > MAX_FILES:
            raise CloneError(
                f"the repository has more than {MAX_FILES} .md and .pdf files"
            )
        if total > MAX_TOTAL_BYTES:
            raise CloneError(
                "the repository's .md and .pdf files are over 100 MB in total"
            )
        files.append((rel.as_posix(), path.read_bytes()))
    return files, skipped


async def clone_files(url: str, repo_ref: str | None) -> ClonedFiles:
    """Shallow-clone, read the commit and the files, and always delete the clone."""
    env = git_env(url, settings.GITLAB_TOKEN)
    tmp = tempfile.mkdtemp(prefix="qna-clone-")
    try:
        dest = os.path.join(tmp, "repo")
        await run_git(
            clone_command(url, repo_ref, dest), env, settings.RAG_CLONE_TIMEOUT_S
        )
        sha = await run_git(["git", "-C", dest, "rev-parse", "HEAD"], env, 30)
        files, skipped = await asyncio.to_thread(collect_files, Path(dest))
        return ClonedFiles(sha, files, skipped)
    finally:
        await asyncio.to_thread(shutil.rmtree, tmp, True)
