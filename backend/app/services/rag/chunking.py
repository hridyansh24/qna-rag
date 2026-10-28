"""
Fallback chunking inside structural sections (docs/design-rag.md §7.2, §7.3).

Structural splitters (services/rag/sources/) turn a document into
non-overlapping Sections. A section that fits under the profile's size cap
becomes one chunk; a larger one is cut by the profile's fallback chunker.
Every chunker returns Spans: character offsets into the whole document text,
never copied strings, so line numbers, pages and Text Fragments can all be
derived from offsets later (services/rag/citations.py).

Sizes are counted in MiniLM tokens for every profile, so the `sliding-window`
and `embedding-alt` profiles produce byte-identical chunks and T6's embedding
axis changes only the embedding model.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from tokenizers import Tokenizer

TOKENIZER_PATH = Path(__file__).parent / "assets" / "minilm-tokenizer.json"

# Every token count in a profile must be at most this (§7.4). MiniLM reads
# only its first 256 word pieces, so a bigger chunk would be embedded from
# its start alone.
MAX_TOKENS = 250


@dataclass(frozen=True)
class Span:
    """A chunk's place in the document text. `char_end` is exclusive."""

    char_start: int
    char_end: int


@dataclass(frozen=True)
class Section:
    """
    A structural section of the document text, with its heading path.
    `heading` is the offsets of the section's heading block (web pages use
    it for Text Fragments, §5.1). A `heading_only` section has nothing but
    its heading and produces no chunk.
    """

    char_start: int
    char_end: int
    path: str
    heading: tuple[int, int] | None = None
    heading_only: bool = False


@lru_cache(maxsize=1)
def tokenizer() -> Tokenizer:
    tok = Tokenizer.from_file(str(TOKENIZER_PATH))
    # The file ships with padding and truncation configured for embedding;
    # counting needs every real token and nothing else.
    tok.no_padding()
    tok.no_truncation()
    return tok


def _encode(text: str) -> list[tuple[int, int]]:
    """Character offsets of each MiniLM token in `text`, no special tokens."""
    return tokenizer().encode(text, add_special_tokens=False).offsets


def count_tokens(text: str) -> int:
    return len(_encode(text))


def chunk_section(
    doc_text: str, section: Section, chunk_size: int, chunk_overlap: int
) -> list[Span]:
    """
    One span for a section that fits in `chunk_size` tokens, sliding-window
    spans for a larger one. A section with no tokens (only whitespace)
    produces nothing. Spans never include the section's leading or trailing
    whitespace.
    """
    text = doc_text[section.char_start : section.char_end]
    offsets = _encode(text)
    if not offsets:
        return []
    if len(offsets) <= chunk_size:
        start, end = offsets[0][0], offsets[-1][1]
        return [Span(section.char_start + start, section.char_start + end)]
    return [
        Span(section.char_start + a, section.char_start + b)
        for a, b in _sliding_window(text, offsets, chunk_size, chunk_overlap)
    ]


def sliding_window(
    doc_text: str, section: Section, chunk_size: int, chunk_overlap: int
) -> list[Span]:
    """Sliding-window spans over a whole section, whatever its size."""
    text = doc_text[section.char_start : section.char_end]
    offsets = _encode(text)
    return [
        Span(section.char_start + a, section.char_start + b)
        for a, b in _sliding_window(text, offsets, chunk_size, chunk_overlap)
    ]


def _sliding_window(
    text: str, offsets: list[tuple[int, int]], chunk_size: int, chunk_overlap: int
) -> list[tuple[int, int]]:
    """
    The §7.3 algorithm, on section-local offsets. A window may start only at
    a word start (a token preceded by whitespace, or the first token) and end
    only just before one, so chunks never cut a word and Text Fragments can
    match them. The end is pulled inward to keep the size cap; the next
    window starts at the last word start at or before `end - chunk_overlap`,
    so consecutive windows touch or overlap and no token is skipped. A run
    of more than `chunk_size` tokens with no whitespace is cut at exactly
    `chunk_size`.
    """
    if not 0 <= chunk_overlap < chunk_size <= MAX_TOKENS:
        raise ValueError(
            f"need 0 <= chunk_overlap < chunk_size <= {MAX_TOKENS}, "
            f"got {chunk_overlap} and {chunk_size}"
        )
    n = len(offsets)
    if n == 0:
        return []
    cuts = [
        i for i in range(n) if i == 0 or text[offsets[i][0] - 1].isspace()
    ]  # word starts, ascending
    spans = []
    start = 0
    while True:
        end = min(start + chunk_size, n)  # exclusive token index
        if end < n:
            end = _last_cut(cuts, start, end) or end
        spans.append((offsets[start][0], offsets[end - 1][1]))
        if end >= n:
            return spans
        nxt = _last_cut(cuts, start, end - chunk_overlap)
        start = nxt if nxt is not None else end


def _last_cut(cuts: list[int], start: int, limit: int) -> int | None:
    """The largest word start c with start < c <= limit, or None."""
    best = None
    for c in cuts:
        if c > limit:
            break
        if c > start:
            best = c
    return best


# ---------------------------------------------------------------------------
# Semantic chunker (§7.3)
# ---------------------------------------------------------------------------

Embed = Callable[[list[str]], Awaitable[list[list[float]]]]

# A sentence ends after . ! or ? followed by whitespace, or at a newline.
_SENTENCE_END = re.compile(r"[.!?]+(?=\s)|\n")


def split_sentences(text: str) -> list[tuple[int, int]]:
    """Sentence spans of `text` (local offsets), trimmed of whitespace, none empty."""
    spans: list[tuple[int, int]] = []
    start = 0
    for match in [*_SENTENCE_END.finditer(text), None]:
        end = match.end() if match else len(text)
        a, b = start, end
        while a < b and text[a].isspace():
            a += 1
        while b > a and text[b - 1].isspace():
            b -= 1
        if a < b:
            spans.append((a, b))
        start = end
    return spans


def breakpoints(sims: list[float], percentile: int) -> list[bool]:
    """
    True where the group should break before sentence i+1: adjacent
    similarity below the section's `percentile`th percentile. Relative, so
    it doesn't depend on the embedding model's score range. Strictly below:
    with ties at the cut (most sims equal), `<=` would break everywhere.
    """
    cut = float(np.percentile(sims, percentile))
    return [sim < cut for sim in sims]


def _cosines(vectors: list[list[float]]) -> list[float]:
    m = np.asarray(vectors, dtype=float)
    m = m / np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-12)
    return [float(x) for x in np.sum(m[:-1] * m[1:], axis=1)]


async def semantic(
    doc_text: str,
    section: Section,
    breakpoint_percentile: int,
    max_tokens: int,
    overflow_size: int,
    overflow_overlap: int,
    embed: Embed,
) -> list[Span]:
    """
    Groups adjacent sentences until their similarity drops into the
    section's lowest `breakpoint_percentile` percent. A group over
    `max_tokens` is re-chunked by a sliding window, never truncated (T6).
    """
    text = doc_text[section.char_start : section.char_end]
    sentences = split_sentences(text)
    if not sentences:
        return []
    groups = [[sentences[0]]]
    if len(sentences) >= 3:
        vectors = await embed([text[a:b] for a, b in sentences])
        for sentence, cut in zip(
            sentences[1:], breakpoints(_cosines(vectors), breakpoint_percentile)
        ):
            if cut:
                groups.append([sentence])
            else:
                groups[-1].append(sentence)
    else:
        groups[0].extend(sentences[1:])

    spans: list[Span] = []
    for group in groups:
        a = section.char_start + group[0][0]
        b = section.char_start + group[-1][1]
        if count_tokens(doc_text[a:b]) <= max_tokens:
            spans.append(Span(a, b))
        else:
            sub = Section(a, b, section.path)
            spans.extend(sliding_window(doc_text, sub, overflow_size, overflow_overlap))
    return spans


async def chunk_with(
    config: dict, doc_text: str, section: Section, embed: Embed
) -> list[Span]:
    """
    Spans for one section under a profile's ChunkerConfig (§7.4). A section
    that fits under the config's size cap is one chunk; the fallback
    chunker runs only on larger ones. Heading-only sections yield nothing.
    """
    if section.heading_only:
        return []
    if config["strategy"] == "sliding_window":
        return chunk_section(
            doc_text, section, config["chunk_size"], config["chunk_overlap"]
        )
    text = doc_text[section.char_start : section.char_end]
    offsets = _encode(text)
    if not offsets:
        return []
    if len(offsets) <= config["max_tokens"]:
        start, end = offsets[0][0], offsets[-1][1]
        return [Span(section.char_start + start, section.char_start + end)]
    overflow = config["overflow"]
    return await semantic(
        doc_text,
        section,
        config["breakpoint_percentile"],
        config["max_tokens"],
        overflow["chunk_size"],
        overflow["chunk_overlap"],
        embed,
    )


def chunk_id(resource_id: int, source_path: str, span: Span) -> str:
    """Deterministic, so re-syncs upsert instead of duplicating (§4.2)."""
    key = f"{resource_id}|{source_path}|{span.char_start}|{span.char_end}"
    return hashlib.sha1(key.encode()).hexdigest()


def qa_chunk_id(question_id: int) -> str:
    return f"qa:{question_id}"
