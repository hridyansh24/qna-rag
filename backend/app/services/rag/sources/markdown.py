"""
Repository markdown: document text and structural split (docs/design-rag.md
§5.2).

The document text is the file itself, decoded and with line endings
normalized, so line n of the text is line n of the file and the embedded
text is the raw markdown.
"""

from __future__ import annotations

import re

from ..chunking import Section

# An ATX heading from # to ####, with up to three spaces of indent and an
# optional closing run of #s. ##### and ###### are content, not boundaries.
_HEADING = re.compile(r"^ {0,3}(#{1,4})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def markdown_text(raw: bytes) -> str:
    """UTF-8, a leading BOM dropped, \\r\\n and \\r turned into \\n. Raises UnicodeDecodeError."""
    text = raw.decode("utf-8").removeprefix("\ufeff")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def split_markdown(text: str, file_name: str) -> list[Section]:
    """
    Non-overlapping sections at # to #### headings, ignoring #s inside
    fenced code blocks. Each section runs from its heading line to the line
    before the next heading, so together they cover the whole text. Lines
    before the first heading take the file name as their path.
    """
    sections: list[Section] = []
    levels: dict[int, str] = {}
    path = file_name
    start = 0
    heading_end: int | None = None  # offset just past the current heading line
    fence: str | None = None

    def close(end: int) -> None:
        if end <= start:
            return
        heading_only = heading_end is not None and not text[heading_end:end].strip()
        sections.append(Section(start, end, path, heading_only=heading_only))

    offset = 0
    # Split on "\n" only, as LineIndex counts lines; str.splitlines() would
    # also split on \u2028 and friends.
    for body in text.split("\n"):
        line_start, offset = offset, offset + len(body) + 1
        fence_match = _FENCE.match(body)
        if fence is not None:
            if (
                fence_match
                and fence_match.group(1)[0] == fence[0]
                and len(fence_match.group(1)) >= len(fence)
            ):
                fence = None
            continue
        if fence_match:
            fence = fence_match.group(1)
            continue
        match = _HEADING.match(body)
        if not match:
            continue
        close(line_start)
        level = len(match.group(1))
        levels[level] = (match.group(2) or "").strip()
        for deeper in [lv for lv in levels if lv > level]:
            del levels[deeper]
        path = (
            " › ".join(levels[lv] for lv in sorted(levels) if levels[lv]) or file_name
        )
        start, heading_end = line_start, offset
    close(len(text))
    return sections
