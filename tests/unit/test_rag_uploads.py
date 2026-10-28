"""
Unit tests for upload storage (backend/app/services/rag/sources/uploads.py).

Covers the design's §13 "upload path traversal rejection" item plus the rest
of the §5.5/§7.1 rules: stored paths keep the staff-entered repo-relative
path (the harness's substring match depends on it), unsafe zip entries
reject the whole upload, wrong-type entries are skipped, the size caps count
real bytes, a re-upload replaces files atomically, and serving never leaves
the resource's own directory.
"""

from __future__ import annotations

import io
import stat
import zipfile

import pytest
from app.common.exceptions import NotFoundError
from app.services.rag.sources import uploads
from app.services.rag.sources.uploads import (
    UploadValidationError,
    iter_stored_files,
    media_type_for,
    normalize_source_path,
    resolve_stored_file,
    store_upload,
)


@pytest.fixture(autouse=True)
def resource_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(uploads.settings, "RESOURCE_DIR", str(tmp_path / "resources"))
    return tmp_path / "resources"


def make_zip(entries: dict[str, bytes], symlinks: tuple[str, ...] = ()) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
        for name in symlinks:
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "/etc/passwd")
    return buf.getvalue()


# --- source paths ----------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("eval/sample_data/web/syllabus.html", "eval/sample_data/web/syllabus.html"),
        (
            "  eval/sample_data/web/syllabus.html  ",
            "eval/sample_data/web/syllabus.html",
        ),
    ],
)
def test_normalize_file_path(raw, expected):
    assert normalize_source_path(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("eval/sample_data/repo/", "eval/sample_data/repo/"),
        ("eval/sample_data/repo", "eval/sample_data/repo/"),
        ("", ""),
    ],
)
def test_normalize_directory_path(raw, expected):
    assert normalize_source_path(raw, is_directory=True) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "/etc/passwd",
        "../secrets.md",
        "a/../../b.md",
        "a//b.md",
        "./a.md",
        "C:/x.md",
        "a\\b.md",
        "a\x00b.md",
        "",
        "x" * 600 + ".md",
    ],
)
def test_normalize_rejects_unsafe_paths(raw):
    with pytest.raises(UploadValidationError):
        normalize_source_path(raw)


# --- single files ----------------------------------------------------------


def test_single_html_keeps_full_source_path(resource_dir):
    result = store_upload(
        3,
        "SYLLABUS",
        "syllabus.html",
        b"<h1>Hi</h1>",
        "eval/sample_data/web/syllabus.html",
    )

    assert [f.source_path for f in result.files] == [
        "eval/sample_data/web/syllabus.html"
    ]
    stored = resource_dir / "3" / "eval/sample_data/web/syllabus.html"
    assert stored.read_bytes() == b"<h1>Hi</h1>"


def test_single_file_extension_must_fit_the_resource_type():
    with pytest.raises(UploadValidationError):
        store_upload(1, "SYLLABUS", "notes.md", b"# x", "docs/notes.md")
    with pytest.raises(UploadValidationError):
        store_upload(1, "REPOSITORY", "slides.pdf", b"%PDF", "lecture/slides.md")


def test_qa_history_does_not_accept_uploads():
    with pytest.raises(UploadValidationError):
        store_upload(1, "QA_HISTORY", "x.md", b"x", "x.md")


def test_zip_only_for_repositories():
    with pytest.raises(UploadValidationError):
        store_upload(1, "SCHEDULE", "web.zip", make_zip({"a.html": b"x"}), "web/")


# --- zips ------------------------------------------------------------------


def test_zip_prefixes_base_and_skips_other_files(resource_dir):
    content = make_zip(
        {
            "p2-buzzer/instructions.md": b"# P2",
            "lecture-10/slides.pdf": b"%PDF-1.4",
            "p2-buzzer/logo.png": b"\x89PNG",
            "__MACOSX/p2-buzzer/._instructions.md": b"junk",
            "p2-buzzer/.DS_Store": b"junk",
        }
    )

    result = store_upload(
        5, "REPOSITORY", "repo.zip", content, "eval/sample_data/repo/"
    )

    assert [f.source_path for f in result.files] == [
        "eval/sample_data/repo/lecture-10/slides.pdf",
        "eval/sample_data/repo/p2-buzzer/instructions.md",
    ]
    # Junk (__MACOSX/, dot-files) is dropped silently; only other types are listed.
    assert result.skipped == [
        {"path": "p2-buzzer/logo.png", "reason": "unsupported type"}
    ]
    assert [p for p, _ in iter_stored_files(5)] == [f.source_path for f in result.files]


def test_zip_skips_dot_folders_silently(resource_dir):
    content = make_zip(
        {
            "notes.md": b"# Notes",
            ".git/HEAD.md": b"junk",
            "docs/.hidden/secret.md": b"junk",
            "p2-buzzer/": b"",  # a directory entry
        }
    )
    result = store_upload(
        5, "REPOSITORY", "repo.zip", content, "eval/sample_data/repo/"
    )
    assert [f.source_path for f in result.files] == ["eval/sample_data/repo/notes.md"]
    assert result.skipped == []


def test_finder_zip_top_folder_matching_the_base_is_stripped(resource_dir):
    content = make_zip(
        {
            "repo/p2-buzzer/instructions.md": b"# P2",
            "repo/lecture-10/slides.pdf": b"%PDF-1.4",
            "__MACOSX/repo/._p2-buzzer": b"junk",
        }
    )
    result = store_upload(
        5, "REPOSITORY", "repo.zip", content, "eval/sample_data/repo/"
    )
    assert [f.source_path for f in result.files] == [
        "eval/sample_data/repo/lecture-10/slides.pdf",
        "eval/sample_data/repo/p2-buzzer/instructions.md",
    ]


def test_top_folder_not_matching_the_base_is_kept(resource_dir):
    content = make_zip(
        {"p2-buzzer/instructions.md": b"# P2", "p2-buzzer/rubric.md": b"#"}
    )
    result = store_upload(5, "REPOSITORY", "p2.zip", content, "eval/sample_data/repo/")
    assert [f.source_path for f in result.files] == [
        "eval/sample_data/repo/p2-buzzer/instructions.md",
        "eval/sample_data/repo/p2-buzzer/rubric.md",
    ]


def test_unsafe_entry_fails_even_next_to_junk_and_good_files(resource_dir):
    content = make_zip({"ok.md": b"# ok", "__MACOSX/../../evil.md": b"x"})
    with pytest.raises(UploadValidationError):
        store_upload(5, "REPOSITORY", "repo.zip", content, "eval/sample_data/repo/")


@pytest.mark.parametrize(
    "entries, symlinks",
    [
        ({"../evil.md": b"x"}, ()),
        ({"a/../../evil.md": b"x"}, ()),
        ({"/abs/evil.md": b"x"}, ()),
        ({"ok.md": b"x"}, ("link.md",)),
    ],
)
def test_unsafe_zip_entries_reject_the_whole_upload(entries, symlinks, resource_dir):
    with pytest.raises(UploadValidationError):
        store_upload(6, "REPOSITORY", "repo.zip", make_zip(entries, symlinks), "base/")
    assert not (resource_dir / "6").exists()
    assert not any(p.name.startswith("evil") for p in resource_dir.rglob("*"))


def test_zip_with_no_usable_files_is_rejected():
    with pytest.raises(UploadValidationError):
        store_upload(1, "REPOSITORY", "repo.zip", make_zip({"a.txt": b"x"}), "")


def test_corrupt_zip_is_rejected():
    with pytest.raises(UploadValidationError):
        store_upload(1, "REPOSITORY", "repo.zip", b"not a zip", "")


def test_zip_entry_count_cap(monkeypatch):
    monkeypatch.setattr(uploads, "MAX_ZIP_ENTRIES", 2)
    content = make_zip({"a.md": b"a", "b.md": b"b", "c.md": b"c"})
    with pytest.raises(UploadValidationError):
        store_upload(1, "REPOSITORY", "repo.zip", content, "")


def test_uncompressed_size_cap_counts_real_bytes(monkeypatch, resource_dir):
    monkeypatch.setattr(uploads, "MAX_UNCOMPRESSED_BYTES", 1000)
    content = make_zip({"big.md": b"x" * 5000})  # compresses to a few bytes
    with pytest.raises(UploadValidationError):
        store_upload(7, "REPOSITORY", "repo.zip", content, "")
    assert not (resource_dir / "7").exists()


# --- replacing -------------------------------------------------------------


def test_reupload_replaces_files_and_failed_reupload_keeps_old_ones():
    store_upload(8, "REPOSITORY", "r.zip", make_zip({"old.md": b"old"}), "base/")
    store_upload(8, "REPOSITORY", "r.zip", make_zip({"new.md": b"new"}), "base/")
    assert [p for p, _ in iter_stored_files(8)] == ["base/new.md"]

    with pytest.raises(UploadValidationError):
        store_upload(8, "REPOSITORY", "r.zip", make_zip({"../x.md": b"x"}), "base/")
    assert [p for p, _ in iter_stored_files(8)] == ["base/new.md"]


# --- serving ---------------------------------------------------------------


def test_resolve_stored_file_and_media_types():
    store_upload(
        9, "REPOSITORY", "r.zip", make_zip({"a.md": b"# a", "s.pdf": b"%PDF"}), "repo/"
    )

    assert resolve_stored_file(9, "repo/a.md").read_bytes() == b"# a"
    assert media_type_for("repo/a.md") == "text/plain; charset=utf-8"
    assert media_type_for("syllabus.html") == "text/plain; charset=utf-8"
    assert media_type_for("repo/s.pdf") == "application/pdf"


@pytest.mark.parametrize(
    "path",
    ["../9/repo/a.md", "repo/../../etc/passwd", "repo/missing.md", "/etc/passwd"],
)
def test_resolve_refuses_traversal_and_missing_files(path):
    store_upload(10, "REPOSITORY", "r.zip", make_zip({"a.md": b"# a"}), "repo/")
    with pytest.raises(NotFoundError):
        resolve_stored_file(10, path)
