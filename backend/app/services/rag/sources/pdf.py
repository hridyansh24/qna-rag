"""
Repository PDFs: document text with a page-offset table, one section per
page (docs/design-rag.md §5.3). Chunks never cross a page, so a chunk's page
is always exact.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from ..chunking import Section


class UnreadablePdf(Exception):
    """The file is skipped with this reason (§7.1)."""


@dataclass(frozen=True)
class PdfDocument:
    text: str
    page_starts: list[int]  # offset where each page's text begins


def pdf_document(raw: bytes) -> PdfDocument:
    try:
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted and not reader.decrypt(""):
            raise UnreadablePdf("encrypted PDF")
        pages = [
            (page.extract_text() or "").replace("\r\n", "\n").replace("\r", "\n")
            for page in reader.pages
        ]
    except UnreadablePdf:
        raise
    except (PyPdfError, ValueError, KeyError, TypeError) as exc:
        # pypdf raises a range of errors on corrupt files; DependencyError
        # (AES without `cryptography`) is a PyPdfError too.
        raise UnreadablePdf(f"unreadable PDF ({type(exc).__name__})") from exc
    if not any(p.strip() for p in pages):
        raise UnreadablePdf("no extractable text")

    starts, offset = [], 0
    for page in pages:
        starts.append(offset)
        offset += len(page) + 2  # the joining "\n\n"
    return PdfDocument("\n\n".join(pages), starts)


def split_pages(doc: PdfDocument) -> list[Section]:
    """One section per page; an empty page's section yields no chunk."""
    ends = [s - 2 for s in doc.page_starts[1:]] + [len(doc.text)]
    return [
        Section(start, end, f"page {n}")
        for n, (start, end) in enumerate(zip(doc.page_starts, ends, strict=True), 1)
    ]
