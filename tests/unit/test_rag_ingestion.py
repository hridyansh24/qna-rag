"""
Unit tests for building chunk records from stored uploads
(docs/design-rag.md §4.2, §5, §7.1, §7.5), on the real eval sample data with
a fake embedder.

No Docker stack required.

Run with:
    cd tests/unit && pytest test_rag_ingestion.py -v
"""

from __future__ import annotations

import io
import pathlib
import zipfile

import pytest
from app.services.rag import ingestion
from app.services.rag.chunking import count_tokens
from app.services.rag.sources import uploads, web
from app.services.resource_service import PRESETS
from pypdf import PdfWriter

SAMPLE = pathlib.Path(__file__).parents[2] / "eval" / "sample_data"
SYNC_ID = "f" * 32


@pytest.fixture(autouse=True)
def resource_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(uploads.settings, "RESOURCE_DIR", str(tmp_path / "resources"))


def profile(name: str) -> ingestion.ProfileSnapshot:
    preset = next(p for p in PRESETS if p["name"] == name)
    return ingestion.ProfileSnapshot(
        name, preset["embedding_model"], preset["chunking"], f"qna_c1__{name}"
    )


def resource(rid: int, rtype: str, source_path: str) -> ingestion.ResourceSnapshot:
    names = {"REPOSITORY": "Course repository", "SYLLABUS": "Syllabus"}
    return ingestion.ResourceSnapshot(
        rid, 1, rtype, "UPLOAD", names[rtype], None, source_path
    )


async def fake_embed(texts):
    return [[float(len(t) % 7), 1.0, float("Slip" in t)] for t in texts]


def repo_zip(extra: dict[str, bytes] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path in sorted((SAMPLE / "repo").rglob("*")):
            if path.is_file():
                zf.write(path, f"repo/{path.relative_to(SAMPLE / 'repo').as_posix()}")
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return buf.getvalue()


def encrypted_pdf() -> bytes:
    writer = PdfWriter(clone_from=SAMPLE / "repo" / "lecture-10" / "slides.pdf")
    writer.encrypt(user_password="secret", algorithm="RC4-128")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


@pytest.fixture
def repo_records():
    """The repository uploaded as a Finder-style zip, plus two unreadable files."""
    base = "eval/sample_data/repo/"
    uploads.store_upload(
        7,
        "REPOSITORY",
        "repo.zip",
        repo_zip(
            {"repo/bad/latin1.md": b"caf\xe9", "repo/bad/locked.pdf": encrypted_pdf()}
        ),
        base,
    )
    return resource(7, "REPOSITORY", base)


def assert_chroma_safe(meta: dict) -> None:
    assert all(isinstance(v, str | int | float | bool) for v in meta.values()), meta


@pytest.mark.parametrize("name", ["sliding-window", "type-tailored"])
async def test_repository_records(repo_records, name):
    out = await ingestion.extract(repo_records, profile(name), SYNC_ID, fake_embed)

    assert out.skipped == [
        {"path": "eval/sample_data/repo/bad/latin1.md", "reason": "not valid UTF-8"},
        {"path": "eval/sample_data/repo/bad/locked.pdf", "reason": "encrypted PDF"},
    ]
    ids = [r.id for r in out.records]
    assert len(ids) == len(set(ids))
    types = {r.metadata["resource_type"] for r in out.records}
    assert types == {"repo_markdown", "repo_pdf"}
    for r in out.records:
        meta = r.metadata
        assert_chroma_safe(meta)
        assert (
            meta["source_path"] in meta["source_url"]
        )  # the harness's substring check
        assert (
            meta["source_url"]
            == f"/api/courses/1/resources/7/files/{meta['source_path']}"
        )
        assert meta["source_path"] == "eval/sample_data/repo/" + meta["rel_path"]
        assert count_tokens(r.text) <= 250
        if meta["resource_type"] == "repo_markdown":
            a, b = meta["line_start"], meta["line_end"]
            assert meta["citation_url"].endswith(f"?lines={a}-{b}")
            assert (
                meta["label"] == f"Course repository: {meta['rel_path']}, lines {a}–{b}"
            )
        else:
            assert meta["citation_url"].endswith(f"?page={meta['page']}")
            assert "section" not in meta


async def test_markdown_lines_point_at_the_chunk_text(repo_records):
    out = await ingestion.extract(
        repo_records, profile("sliding-window"), SYNC_ID, fake_embed
    )
    raw = (SAMPLE / "repo" / "p2-buzzer" / "instructions.md").read_text().split("\n")
    md = [
        r
        for r in out.records
        if r.metadata.get("rel_path") == "p2-buzzer/instructions.md"
    ]
    assert md
    for r in md:
        a, b = r.metadata["line_start"], r.metadata["line_end"]
        cited = "\n".join(raw[a - 1 : b])
        assert r.text.split("\n")[0] in cited and r.text.split("\n")[-1] in cited


async def test_syllabus_records_index_the_document_text():
    path = "eval/sample_data/web/syllabus.html"
    raw = (SAMPLE / "web" / "syllabus.html").read_bytes()
    uploads.store_upload(8, "SYLLABUS", "syllabus.html", raw, path)
    out = await ingestion.extract(
        resource(8, "SYLLABUS", path), profile("sliding-window"), SYNC_ID, fake_embed
    )
    text = web.document_text(raw)  # what ?format=text serves
    assert out.records and out.skipped == []
    for r in out.records:
        meta = r.metadata
        assert_chroma_safe(meta)
        assert text[meta["char_start"] : meta["char_end"]] == r.text
        assert meta["citation_url"] == (
            f"/student/sources/8/{path}?chars={meta['char_start']}-{meta['char_end']}"
        )
        assert meta["text_start"] and "\n" not in meta["text_start"]
        assert meta["label"] == f"Syllabus › {meta['section']}"
        assert path in meta["source_url"]


async def test_a_run_that_skips_every_file_fails():
    uploads.store_upload(9, "REPOSITORY", "bad.md", b"caf\xe9", "docs/bad.md")
    with pytest.raises(ingestion.IngestionError, match="no readable files"):
        await ingestion.extract(
            resource(9, "REPOSITORY", "docs/bad.md"),
            profile("sliding-window"),
            SYNC_ID,
            fake_embed,
        )


async def test_single_file_rel_path_is_its_name():
    uploads.store_upload(
        10, "REPOSITORY", "notes.md", b"# Notes\nSlip days.\n", "docs/notes.md"
    )
    out = await ingestion.extract(
        resource(10, "REPOSITORY", "docs/notes.md"),
        profile("sliding-window"),
        SYNC_ID,
        fake_embed,
    )
    assert [r.metadata["rel_path"] for r in out.records] == ["notes.md"]


def test_qa_record_is_one_unsplit_chunk():
    from app.services.rag.sources.qa_history import QaThread

    thread = QaThread(
        7, "Reset migrations?", "How do I reset?", "AI", "Run alembic downgrade base."
    )
    record = ingestion.qa_record(
        1, 3, "Historical Q&A", "sliding-window", SYNC_ID, thread
    )
    assert record.id == "qa:7"
    assert record.text == (
        "Question: Reset migrations?\nHow do I reset?\n\n"
        "Accepted answer (AI-generated): Run alembic downgrade base."
    )
    assert (
        record.metadata["citation_url"]
        == record.metadata["source_url"]
        == "/student/questions/7"
    )
    assert record.metadata["label"] == "Q&A: Reset migrations?"
    assert_chroma_safe(record.metadata)


def test_errors_are_scrubbed_of_the_token(monkeypatch):
    import base64

    monkeypatch.setattr(ingestion.settings, "GITLAB_TOKEN", "glpat-SECRET")
    header = base64.b64encode(b"oauth2:glpat-SECRET").decode()
    assert ingestion.scrub(f"fatal: glpat-SECRET and {header}") == "fatal: *** and ***"
