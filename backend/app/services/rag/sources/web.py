"""
Syllabus and schedule pages: HTML cleaning and structural split
(docs/design-rag.md §5.1).

`clean_html` turns a page into its **document text**: a list of blocks joined
with "\\n", each with its offsets. `split_sections` cuts that text into
non-overlapping sections at h1–h4 headings. Both the ingestion of uploaded
or fetched pages and the file endpoint's `?format=text` use `clean_html`, so
stored offsets index straight into what the viewer shows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import lxml.html

from ..chunking import Section

REMOVED_TAGS = {
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "nav",
    "header",
    "footer",
}
BLOCK_TAGS = {
    "p",
    "li",
    "td",
    "th",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "pre",
    "blockquote",
    "dd",
    "dt",
    "div",
    "section",
    "main",
    "article",
    "ul",
    "ol",
    "table",
    "tr",
}
SECTION_LEVELS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4}
_DISPLAY_NONE = re.compile(r"display\s*:\s*none", re.IGNORECASE)


@dataclass(frozen=True)
class Block:
    start: int
    end: int  # exclusive
    heading_level: int | None = None  # 1–4 for an h1–h4 block


@dataclass(frozen=True)
class WebDocument:
    text: str
    blocks: list[Block]
    title: str


class _Collector:
    """Walks the tree once, in document order, collecting text into blocks."""

    def __init__(self) -> None:
        self.blocks: list[tuple[str, int | None]] = []
        self._parts: list[str] = []
        self._pre = 0
        self._heading: int | None = None

    def text(self, value: str | None) -> None:
        if value:
            self._parts.append(value)

    def end_block(self) -> None:
        raw = "".join(self._parts)
        self._parts = []
        heading, self._heading = self._heading, None
        if self._pre:
            # Inside <pre> each line is its own block and keeps its spacing.
            for line in raw.split("\n"):
                if line.strip():
                    self.blocks.append((line.rstrip(), None))
            return
        collapsed = " ".join(raw.split())
        if collapsed:
            self.blocks.append((collapsed, heading))

    def visit(self, el) -> None:
        if not isinstance(el.tag, str):  # comment or processing instruction
            self.text(el.tail)
            return
        tag = el.tag.lower()
        if tag == "br":
            self.end_block()
            self.text(el.tail)
            return
        is_block = tag in BLOCK_TAGS
        if is_block:
            self.end_block()
            self._heading = SECTION_LEVELS.get(tag)
        if tag == "pre":
            self._pre += 1
        self.text(el.text)
        for child in el:
            self.visit(child)
        if is_block:
            self.end_block()
        if tag == "pre":
            self._pre -= 1
        self.text(el.tail)


def _is_hidden(el) -> bool:
    return el.get("hidden") is not None or bool(
        _DISPLAY_NONE.search(el.get("style") or "")
    )


def clean_html(raw: bytes | str) -> WebDocument:
    """The page's document text, blocks and <title> (§5.1)."""
    root = lxml.html.document_fromstring(raw)
    title_el = root.find(".//title")
    title = " ".join((title_el.text_content() if title_el is not None else "").split())
    body = root.find("body")
    if body is None:
        body = root
    doomed = [
        el
        for el in body.iter()
        if isinstance(el.tag, str)
        and (el.tag.lower() in REMOVED_TAGS or _is_hidden(el))
    ]
    for el in doomed:
        if el.getparent() is not None:
            el.drop_tree()  # keeps the element's tail text

    collector = _Collector()
    collector.visit(body)
    collector.end_block()

    blocks: list[Block] = []
    pieces: list[str] = []
    offset = 0
    for text, heading in collector.blocks:
        blocks.append(Block(offset, offset + len(text), heading))
        pieces.append(text)
        offset += len(text) + 1  # the joining "\n"
    return WebDocument("\n".join(pieces), blocks, title)


def document_text(raw: bytes | str) -> str:
    """What the file endpoint returns for `?format=text` (§5.5)."""
    return clean_html(raw).text


def split_sections(doc: WebDocument) -> list[Section]:
    """
    Non-overlapping sections at h1–h4 headings, covering every block exactly
    once. Each section's path is the heading path; text before the first
    heading takes the page title. A section holding only its heading is
    marked `heading_only` and produces no chunk.
    """
    sections: list[Section] = []
    levels: dict[int, str] = {}
    current: list[Block] = []
    path = doc.title or "Untitled page"
    heading: Block | None = None

    def close() -> None:
        if not current:
            return
        sections.append(
            Section(
                current[0].start,
                current[-1].end,
                path,
                heading=(heading.start, heading.end) if heading else None,
                heading_only=heading is not None and len(current) == 1,
            )
        )

    for block in doc.blocks:
        if block.heading_level is None:
            current.append(block)
            continue
        close()
        level = block.heading_level
        levels[level] = doc.text[block.start : block.end]
        for deeper in [lv for lv in levels if lv > level]:
            del levels[deeper]
        path = " › ".join(levels[lv] for lv in sorted(levels))
        heading = block
        current = [block]
    close()
    return sections
