"""
Upload fallback storage for course resources (docs/design-rag.md §5.5, §7.1).

Staff upload a resource as one file or, for a repository, a .zip. Files are
stored under RESOURCE_DIR/{resource_id}/{source_path}, where source_path is
the repo-relative path staff enter on the upload form (for a zip, a base
directory plus each entry's path inside the zip). Keeping that full path is
what lets compare_harness.py's substring check (`expected_source in
source_url`) match, e.g. `eval/sample_data/repo/p2-buzzer/instructions.md`.

This module is pure storage and validation: no database, no parsing. The
resources router calls `store_upload()` / `replace_upload()`, ingestion reads
files back with `iter_stored_files()`, and the file endpoint serves them with
`resolve_stored_file()` + `media_type_for()`.

Safety rules:
- source paths are relative POSIX paths with no `..`, no empty segments, no
  backslashes and no control characters;
- a zip entry that is absolute, climbs out with `..`, or is a symlink rejects
  the whole upload (422) — it's an attack or a broken archive, not content;
- junk is skipped silently: directory entries, `__MACOSX/`, and any entry
  with a path segment starting with `.` (`.DS_Store`, `._x.md`, `.git/…`);
- other file types (.png, .txt, ...) are skipped and reported in `skipped`;
- one shared top-level folder is stripped when its name equals the base's
  last segment, so a Finder zip of `repo/` with base `eval/sample_data/repo/`
  isn't stored under `…/repo/repo/` (§5.5 rule 4);
- caps on the upload (25 MB, enforced by the caller via read_upload_capped),
  the number of zip entries (1000) and the total uncompressed size (100 MB),
  counted from the bytes actually extracted, not the sizes the zip claims;
- serving resolves the path and refuses anything outside the resource's own
  directory.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import stat
import uuid
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from ....common.exceptions import NotFoundError, QnaError
from ....config import settings

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_ZIP_ENTRIES = 1000
MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_SOURCE_PATH_LEN = 512  # course_resources.upload_source_path is VARCHAR(512)
_COPY_CHUNK = 64 * 1024

# What each resource type may contain (§7.1).
WEB_EXTENSIONS = {".html", ".htm"}
REPO_EXTENSIONS = {".md", ".pdf"}
ALLOWED_SINGLE_FILE = {
    "SYLLABUS": WEB_EXTENSIONS,
    "SCHEDULE": WEB_EXTENSIONS,
    "REPOSITORY": REPO_EXTENSIONS,
}

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class UploadValidationError(QnaError):
    """The upload or its source path is unacceptable (422)."""

    def __init__(self, message: str):
        super().__init__("INVALID_UPLOAD", message, 422)


@dataclass(frozen=True)
class StoredFile:
    source_path: str  # e.g. "eval/sample_data/repo/p2-buzzer/instructions.md"
    size: int

    @property
    def extension(self) -> str:
        return PurePosixPath(self.source_path).suffix.lower()


@dataclass
class UploadResult:
    files: list[StoredFile] = field(default_factory=list)
    # Zip entries of other types, as {"path": entry name, "reason": ...} (§9.6).
    skipped: list[dict[str, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def normalize_source_path(raw: str, *, is_directory: bool = False) -> str:
    """
    Validate and normalize a staff-entered source path.

    Returns a relative POSIX path. A directory (the zip base) keeps a trailing
    "/", or is "" for "store entries at their zip paths as-is".
    """
    path = (raw or "").strip()
    if _CONTROL_CHARS.search(path):
        raise UploadValidationError("Source path contains control characters")
    if "\\" in path:
        raise UploadValidationError("Source path must use '/' separators")
    if path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        raise UploadValidationError(
            "Source path must be relative, e.g. eval/sample_data/repo/"
        )

    if is_directory:
        path = path.rstrip("/")  # a base directory may end in "/"
        if not path:
            return ""
    elif not path:
        raise UploadValidationError("Source path is required for a single-file upload")

    parts = path.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise UploadValidationError(
            "Source path can't contain empty, '.' or '..' segments"
        )
    normalized = "/".join(parts) + ("/" if is_directory else "")
    if len(normalized) > MAX_SOURCE_PATH_LEN:
        raise UploadValidationError(
            f"Source path is longer than {MAX_SOURCE_PATH_LEN} characters"
        )
    return normalized


def resource_root(resource_id: int) -> Path:
    return Path(settings.RESOURCE_DIR) / str(int(resource_id))


def _safe_join(root: Path, source_path: str) -> Path:
    """root/source_path, refusing anything that resolves outside root."""
    target = (root / source_path).resolve()
    root_resolved = root.resolve()
    if target != root_resolved and root_resolved not in target.parents:
        raise UploadValidationError("Path escapes the resource directory")
    return target


# ---------------------------------------------------------------------------
# Storing
# ---------------------------------------------------------------------------


def store_upload(
    resource_id: int,
    resource_type: str,
    filename: str,
    content: bytes,
    source_path: str,
) -> UploadResult:
    """
    Validate and store a new upload for `resource_id`, replacing anything
    already stored for it. The caller has already capped `content` at
    MAX_UPLOAD_BYTES with read_upload_capped().
    """
    root = resource_root(resource_id)
    staging = root.parent / f".staging-{resource_id}-{uuid.uuid4().hex}"
    try:
        result = _extract(resource_type, filename, content, source_path, staging)
        _swap_into_place(staging, root)
        return result
    finally:
        shutil.rmtree(staging, ignore_errors=True)


# Re-uploading (PUT …/resources/{rid}/upload) is the same operation: the new
# files replace the old ones atomically, so a failed re-upload changes nothing.
replace_upload = store_upload


def delete_stored_files(resource_id: int) -> None:
    shutil.rmtree(resource_root(resource_id), ignore_errors=True)


def _extract(
    resource_type: str, filename: str, content: bytes, source_path: str, dest: Path
) -> UploadResult:
    if resource_type not in ALLOWED_SINGLE_FILE:
        raise UploadValidationError(
            f"Resource type {resource_type} doesn't accept uploads"
        )
    if len(content) > MAX_UPLOAD_BYTES:
        raise UploadValidationError("Upload exceeds the 25 MB limit")
    is_zip = PurePosixPath(filename or "").suffix.lower() == ".zip"

    dest.mkdir(parents=True, exist_ok=False)
    if is_zip:
        if resource_type != "REPOSITORY":
            raise UploadValidationError("Only repository resources accept a .zip")
        base = normalize_source_path(source_path, is_directory=True)
        return _extract_zip(content, base, dest)

    path = normalize_source_path(source_path)
    allowed = ALLOWED_SINGLE_FILE[resource_type]
    ext = PurePosixPath(path).suffix.lower()
    if ext not in allowed:
        raise UploadValidationError(
            f"A {resource_type.lower()} upload must be one of {sorted(allowed)}; "
            f"the source path ends in '{ext or '(none)'}'"
        )
    uploaded_ext = PurePosixPath(filename or "").suffix.lower()
    if (
        uploaded_ext
        and uploaded_ext != ext
        and not (uploaded_ext in WEB_EXTENSIONS and ext in WEB_EXTENSIONS)
    ):
        raise UploadValidationError(
            f"The uploaded file is '{uploaded_ext}' but the source path ends in '{ext}'"
        )
    target = _safe_join(dest, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return UploadResult(files=[StoredFile(path, len(content))])


def _is_junk(info: zipfile.ZipInfo, parts: list[str]) -> bool:
    return (
        info.is_dir()
        or "__MACOSX" in parts
        or any(part.startswith(".") for part in parts)
    )


def _extract_zip(content: bytes, base: str, dest: Path) -> UploadResult:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise UploadValidationError("The .zip file is corrupt or not a zip")

    with archive:
        entries = archive.infolist()
        if len(entries) > MAX_ZIP_ENTRIES:
            raise UploadValidationError(
                f"The .zip has {len(entries)} entries; the limit is {MAX_ZIP_ENTRIES}"
            )

        # Rule 1: one unsafe entry fails the whole upload, before anything
        # is written. Then rules 2 and 3: junk silently, other types listed.
        for info in entries:
            _check_zip_entry_is_safe(info)
        result = UploadResult()
        kept: list[tuple[zipfile.ZipInfo, list[str]]] = []
        for info in entries:
            # A leading "./" is only a spelling of the zip's root.
            parts = [p for p in info.filename.split("/") if p not in ("", ".")]
            if not parts or _is_junk(info, parts):
                continue
            if PurePosixPath(parts[-1]).suffix.lower() not in REPO_EXTENSIONS:
                result.skipped.append(
                    {"path": info.filename, "reason": "unsupported type"}
                )
                continue
            kept.append((info, parts))
        if not kept:
            raise UploadValidationError("The .zip contains no .md or .pdf files")

        # Rule 4: strip one shared top-level folder named like the base's
        # last segment (a Finder zip of the folder itself).
        base_last = base.rstrip("/").rsplit("/", 1)[-1]
        tops = {parts[0] for _, parts in kept}
        if (
            base_last
            and tops == {base_last}
            and all(len(parts) > 1 for _, parts in kept)
        ):
            kept = [(info, parts[1:]) for info, parts in kept]

        total = 0
        for info, parts in kept:
            source_path = base + "/".join(parts)
            if len(source_path) > MAX_SOURCE_PATH_LEN:
                raise UploadValidationError(f"Path too long: {source_path[:80]}…")
            target = _safe_join(dest, source_path)
            target.parent.mkdir(parents=True, exist_ok=True)

            # Count bytes actually written: the sizes in a zip's directory
            # can lie (zip bombs), so they're never trusted.
            written = 0
            with archive.open(info) as src, open(target, "wb") as out:
                while chunk := src.read(_COPY_CHUNK):
                    written += len(chunk)
                    total += len(chunk)
                    if total > MAX_UNCOMPRESSED_BYTES:
                        raise UploadValidationError(
                            "The .zip expands past the 100 MB limit"
                        )
                    out.write(chunk)
            result.files.append(StoredFile(source_path, written))

    result.files.sort(key=lambda f: f.source_path)
    return result


def _check_zip_entry_is_safe(info: zipfile.ZipInfo) -> None:
    name = info.filename
    if name.startswith("/") or "\\" in name or re.match(r"^[A-Za-z]:", name):
        raise UploadValidationError(
            f"Zip entry has an absolute or Windows path: {name}"
        )
    if any(part == ".." for part in name.split("/")):
        raise UploadValidationError(f"Zip entry escapes its directory: {name}")
    if _CONTROL_CHARS.search(name):
        raise UploadValidationError("Zip entry name contains control characters")
    mode = info.external_attr >> 16
    if stat.S_ISLNK(mode):
        raise UploadValidationError(f"Zip entry is a symlink: {name}")


def _swap_into_place(staging: Path, root: Path) -> None:
    """Replace root with staging so readers never see a half-written upload."""
    root.parent.mkdir(parents=True, exist_ok=True)
    old = root.parent / f".old-{root.name}-{uuid.uuid4().hex}"
    if root.exists():
        os.replace(root, old)
    os.replace(staging, root)
    shutil.rmtree(old, ignore_errors=True)


# ---------------------------------------------------------------------------
# Reading back
# ---------------------------------------------------------------------------


def iter_stored_files(resource_id: int) -> Iterator[tuple[str, Path]]:
    """(source_path, absolute path) for every stored file, sorted by path."""
    root = resource_root(resource_id)
    if not root.is_dir():
        return
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        yield path.relative_to(root).as_posix(), path


def resolve_stored_file(resource_id: int, source_path: str) -> Path:
    """The stored file for (resource, path), or 404. Never outside the resource dir."""
    try:
        path = normalize_source_path(source_path)
        target = _safe_join(resource_root(resource_id), path)
    except UploadValidationError:
        raise NotFoundError("File not found")
    if not target.is_file():
        raise NotFoundError("File not found")
    return target


def media_type_for(path: Path | str) -> str:
    """
    Served types (§5.5): markdown and HTML as plain text, so an uploaded HTML
    page never renders on our origin; PDFs as PDFs. Callers also send
    `X-Content-Type-Options: nosniff`.
    """
    ext = PurePosixPath(str(path)).suffix.lower()
    if ext == ".pdf":
        return "application/pdf"
    return "text/plain; charset=utf-8"
