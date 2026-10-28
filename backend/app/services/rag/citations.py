"""
Citation locations, URLs and labels, all built from stored offsets and
metadata (docs/design-rag.md §4.1, §5). The model never writes a URL, line
number or page number.

Offsets follow Python slicing: `char_end` is exclusive, so a chunk's last
line or page is the one containing `char_end - 1`.
"""

from __future__ import annotations

import bisect
import re
from urllib.parse import quote, urlsplit

LABEL_MAX = 255  # post_citations.label is VARCHAR(255)
ELLIPSIS = "…"

# ---------------------------------------------------------------------------
# Offsets → lines and pages
# ---------------------------------------------------------------------------


class LineIndex:
    """Maps document offsets to 1-based line numbers (markdown, §5.2)."""

    def __init__(self, text: str):
        self._starts = [0] + [m.end() for m in re.finditer("\n", text)]

    def line_of(self, offset: int) -> int:
        return bisect.bisect_right(self._starts, offset)

    def lines(self, char_start: int, char_end: int) -> tuple[int, int]:
        """(line_start, line_end), 1-based and inclusive."""
        return self.line_of(char_start), self.line_of(max(char_start, char_end - 1))


class PageIndex:
    """Maps document offsets to 1-based PDF pages (§5.3)."""

    def __init__(self, page_starts: list[int]):
        self._starts = page_starts  # offset where each page's text begins

    def page_of(self, offset: int) -> int:
        return bisect.bisect_right(self._starts, offset)


# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------


def quote_path(path: str) -> str:
    """Percent-encode each `/`-separated segment of a stored path."""
    return "/".join(quote(segment, safe="") for segment in path.split("/"))


def web_url(clone_url: str) -> str:
    """
    A repository's GitLab web URL from its clone URL: a trailing `/`, then
    a trailing `.git`, removed (§5.2). Userinfo, a query or a fragment are
    rejected: registration refuses such URLs, so seeing one here is a bug.
    """
    parts = urlsplit(clone_url)
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("clone URL must not contain userinfo, a query or a fragment")
    url = clone_url.rstrip("/")
    return url.removesuffix(".git")


def repo_markdown_urls(
    web: str, commit_sha: str, path: str, a: int, b: int
) -> tuple[str, str]:
    """(citation_url, source_url). `?plain=1` is required for line anchors."""
    source = f"{web}/-/blob/{commit_sha}/{quote_path(path)}"
    return f"{source}?plain=1#L{a}-{b}", source


def repo_pdf_urls(web: str, commit_sha: str, path: str, page: int) -> tuple[str, str]:
    source = f"{web}/-/raw/{commit_sha}/{quote_path(path)}"
    return f"{source}#page={page}", source


def qa_url(question_id: int) -> str:
    """Both citation_url and source_url for a Q&A chunk (§5.4)."""
    return f"/student/questions/{question_id}"


def upload_source_url(course_id: int, resource_id: int, stored_path: str) -> str:
    """The file API URL, which contains the stored path for the harness (§5.5)."""
    return f"/api/courses/{course_id}/resources/{resource_id}/files/{quote_path(stored_path)}"


def viewer_url(resource_id: int, stored_path: str, query: str) -> str:
    """
    The in-app viewer link stored as an upload's citation_url, with the
    student prefix that each app rewrites to its own base (§5.5, §10).
    `query` is `lines=a-b`, `page=n` or `chars=a-b`.
    """
    return f"/student/sources/{resource_id}/{quote_path(stored_path)}?{query}"


# ---------------------------------------------------------------------------
# Text Fragments (web pages, §5.1)
# ---------------------------------------------------------------------------

FRAGMENT_SHORT_WORDS = 12  # a single-block span this short is quoted whole
FRAGMENT_TERM_WORDS = 6  # otherwise each term is at most this many words


def _words_within(doc_text: str, start: int, end: int) -> list[str]:
    """
    The whole words of doc_text[start:end]. Spans normally begin and end on
    whitespace (§7.3); when one doesn't (an unbroken run longer than the
    chunk size), the cut-off word at that edge is dropped, because a Text
    Fragment term that starts or ends mid-word never matches.
    """
    words = doc_text[start:end].split()
    if len(words) > 1 and start > 0 and not doc_text[start - 1].isspace():
        words = words[1:]
    if len(words) > 1 and end < len(doc_text) and not doc_text[end].isspace():
        words = words[:-1]
    return words


def text_fragment(
    doc_text: str,
    blocks: list[tuple[int, int]],
    char_start: int,
    char_end: int,
    heading_block: tuple[int, int] | None = None,
) -> tuple[str, str | None]:
    """
    (text_start, text_end) for a span of a web page's document text.
    `blocks` are the (start, end) offsets of the document's blocks, in order;
    `heading_block` is the span's section heading, used when the span's own
    first words appear earlier on the page. A term never crosses a block.
    """
    parts = [
        (max(a, char_start), min(b, char_end))
        for a, b in blocks
        if a < char_end and b > char_start
    ]
    if not parts:
        raise ValueError("span overlaps no block")

    if len(parts) == 1:
        words = _words_within(doc_text, *parts[0])
        if len(words) <= FRAGMENT_SHORT_WORDS:
            start_term, end_term = " ".join(words), None
        else:
            start_term = " ".join(words[:FRAGMENT_TERM_WORDS])
            end_term = " ".join(words[-FRAGMENT_TERM_WORDS:])
    else:
        start_term = " ".join(_words_within(doc_text, *parts[0])[:FRAGMENT_TERM_WORDS])
        end_term = " ".join(_words_within(doc_text, *parts[-1])[-FRAGMENT_TERM_WORDS:])

    # A browser highlights the first match. If these words also occur
    # earlier on the page, anchor the start at the section heading instead.
    first = doc_text.lower().find(start_term.lower())
    if heading_block is not None and 0 <= first < parts[0][0]:
        heading_words = _words_within(doc_text, *heading_block)[:FRAGMENT_TERM_WORDS]
        if end_term is None:
            end_term = " ".join(
                _words_within(doc_text, *parts[-1])[-FRAGMENT_TERM_WORDS:]
            )
        start_term = " ".join(heading_words)
    return start_term, end_term


def _fragment_term(term: str) -> str:
    # quote() leaves `-` alone, but it has a meaning in the fragment syntax.
    return quote(term, safe="").replace("-", "%2D")


def fragment_url(url: str, text_start: str, text_end: str | None) -> str:
    fragment = _fragment_term(text_start)
    if text_end:
        fragment += "," + _fragment_term(text_end)
    return f"{url}#:~:text={fragment}"


# ---------------------------------------------------------------------------
# Labels (§4.1)
# ---------------------------------------------------------------------------


def _fit(prefix: str, middle: str, suffix: str) -> str:
    """prefix + middle + suffix within LABEL_MAX, cutting the middle's middle."""
    room = LABEL_MAX - len(prefix) - len(suffix)
    if len(middle) > room:
        keep = max(room - len(ELLIPSIS), 0)
        head = (keep + 1) // 2
        middle = middle[:head] + ELLIPSIS + middle[len(middle) - (keep - head) :]
    return (prefix + middle + suffix)[:LABEL_MAX]


def web_label(display_name: str, section: str) -> str:
    return _fit(f"{display_name} › ", section, "")


def markdown_label(display_name: str, rel_path: str, a: int, b: int) -> str:
    return _fit(f"{display_name}: ", rel_path, f", lines {a}–{b}")


def pdf_label(display_name: str, rel_path: str, page: int) -> str:
    return _fit(f"{display_name}: ", rel_path, f", page {page}")


def qa_label(title: str) -> str:
    return _fit("Q&A: ", title, "")


# ---------------------------------------------------------------------------
# Citations for a posted AI answer (§4.1, §6.4)
# ---------------------------------------------------------------------------

QUOTED_TEXT_CHARS = 600


def location(meta: dict) -> dict:
    """The per-type location stored with a citation (§4.1 `location_json`)."""
    kind = meta.get("resource_type")
    if kind == "repo_markdown":
        return {"lines": [meta.get("line_start"), meta.get("line_end")]}
    if kind == "repo_pdf":
        return {"page": meta.get("page")}
    if kind == "qa_thread":
        return {"question_id": meta.get("question_id")}
    loc = {"text_start": meta.get("text_start"), "text_end": meta.get("text_end")}
    if "char_start" in meta:
        loc["chars"] = [meta["char_start"], meta["char_end"]]
    return loc


def citations_for(chunks: list) -> list[dict]:
    """
    One citation per chunk that went into the prompt, best first. A chunk
    whose citation_url repeats a higher-ranked one is dropped, and ranks are
    renumbered 1…n with no gaps. `chunks` have `.text`, `.metadata` and
    `.similarity`.
    """
    seen: set[str] = set()
    out = []
    for chunk in chunks:
        meta = chunk.metadata
        url = meta.get("citation_url", "")
        if url in seen:
            continue
        seen.add(url)
        out.append(
            {
                "rank": len(out) + 1,
                "resource_id": meta.get("resource_id"),
                "resource_type": meta.get("resource_type", ""),
                "label": str(meta.get("label", ""))[:255],
                "citation_url": url,
                "location_json": location(meta),
                "quoted_text": chunk.text[:QUOTED_TEXT_CHARS],
                "similarity_score": round(chunk.similarity, 4),
            }
        )
    return out
