"""
Unit tests for the fallback chunker (docs/design-rag.md §7.2, §7.3).

No Docker stack required: the MiniLM tokenizer is a vendored file.

Run with:
    cd tests/unit && pytest test_rag_chunking.py -v
"""

from __future__ import annotations

import itertools

import pytest
from app.services.rag.chunking import (
    MAX_TOKENS,
    Section,
    Span,
    breakpoints,
    chunk_id,
    chunk_section,
    chunk_with,
    count_tokens,
    qa_chunk_id,
    semantic,
    sliding_window,
    split_sentences,
)

PROSE = " ".join(
    f"Sentence {i} explains slip days, late penalties, and the hard cutoff for project {i % 4}."
    for i in range(60)
)


def section_of(text: str, path: str = "Doc") -> Section:
    return Section(0, len(text), path)


def test_tokenizer_counts_real_tokens_only():
    # The vendored file pads to 128 and truncates; counting must do neither.
    assert count_tokens("hello world") == 2
    assert count_tokens("word " * 400) == 400


def test_small_section_is_one_span_without_surrounding_whitespace():
    doc = "\n\n  Slip days: 4 per semester.  \n"
    assert chunk_section(doc, section_of(doc), 200, 40) == [Span(4, 30)]


def test_whitespace_only_section_yields_nothing():
    assert chunk_section("   \n  ", section_of("   \n  "), 200, 40) == []


@pytest.mark.parametrize(("size", "overlap"), [(50, 10), (120, 20), (200, 40), (64, 0)])
def test_every_window_respects_the_token_cap(size, overlap):
    spans = sliding_window(PROSE, section_of(PROSE), size, overlap)
    assert len(spans) > 1
    assert all(count_tokens(PROSE[s.char_start : s.char_end]) <= size for s in spans)


def test_window_edges_fall_on_whitespace():
    spans = sliding_window(PROSE, section_of(PROSE), 50, 10)
    for s in spans:
        assert s.char_start == 0 or PROSE[s.char_start - 1].isspace()
        assert s.char_end == len(PROSE) or PROSE[s.char_end].isspace()


@pytest.mark.parametrize("overlap", [0, 10])
def test_no_token_is_skipped(overlap):
    spans = sliding_window(PROSE, section_of(PROSE), 50, overlap)
    for a, b in itertools.pairwise(spans):
        assert b.char_start <= a.char_end + 1  # touching or overlapping
    assert spans[0].char_start == 0 and spans[-1].char_end == len(PROSE)


def test_consecutive_windows_overlap_when_asked():
    spans = sliding_window(PROSE, section_of(PROSE), 50, 10)
    overlaps = [PROSE[b.char_start : a.char_end] for a, b in itertools.pairwise(spans)]
    assert all(count_tokens(o) >= 1 for o in overlaps)


def test_unbroken_run_is_cut_at_exactly_the_cap():
    # Many tokens with no whitespace, like a long URL. (One 2,000-letter word
    # would be a single [UNK] token: WordPiece gives up past 100 characters.)
    doc = "start " + "-".join(["seg"] * 300) + " end"
    spans = sliding_window(doc, section_of(doc), 50, 10)
    inner = [count_tokens(doc[s.char_start : s.char_end]) for s in spans[:-1]]
    assert max(inner) <= 50 and any(n == 50 for n in inner)


def test_spans_are_document_relative():
    doc = "# A\n" + PROSE + "\n# B\n" + PROSE
    first = Section(0, 4 + len(PROSE), "A")
    second = Section(first.char_end + 1, len(doc), "B")
    a_spans = chunk_section(doc, first, 50, 10)
    b_spans = chunk_section(doc, second, 50, 10)
    assert all(
        first.char_start <= s.char_start < s.char_end <= first.char_end for s in a_spans
    )
    assert all(
        second.char_start <= s.char_start < s.char_end <= second.char_end
        for s in b_spans
    )
    ids_a = {chunk_id(1, "eval/sample_data/repo/x.md", s) for s in a_spans}
    ids_b = {chunk_id(1, "eval/sample_data/repo/x.md", s) for s in b_spans}
    assert ids_a.isdisjoint(ids_b)


def test_chunk_ids_are_deterministic():
    span = Span(10, 90)
    assert chunk_id(3, "a/b.md", span) == chunk_id(3, "a/b.md", span)
    assert chunk_id(3, "a/b.md", span) != chunk_id(4, "a/b.md", span)
    assert qa_chunk_id(7) == "qa:7"


@pytest.mark.parametrize(
    ("size", "overlap"), [(40, 40), (40, 50), (MAX_TOKENS + 1, 10), (40, -1)]
)
def test_invalid_window_settings_are_rejected(size, overlap):
    with pytest.raises(ValueError):
        sliding_window(PROSE, section_of(PROSE), size, overlap)


# --- semantic chunker (§7.3) ----------------------------------------------------


def test_split_sentences_keeps_offsets_and_drops_blanks():
    text = "First one. Second?  Third!\n\nFourth line\nv1.2 stays"
    spans = split_sentences(text)
    assert [text[a:b] for a, b in spans] == [
        "First one.",
        "Second?",
        "Third!",
        "Fourth line",
        "v1.2 stays",
    ]


def fake_embedder(topic_of):
    async def embed(texts):
        return [[1.0, 0.0] if topic_of(t) == "a" else [0.0, 1.0] for t in texts]

    return embed


async def test_semantic_breaks_where_adjacent_similarity_drops():
    doc = (
        "Slip days cover lateness. Slip days are limited. Slip days end at cutoff. "
        "Docker runs the stack. Docker uses compose. Docker needs memory."
    )
    spans = await semantic(
        doc,
        section_of(doc),
        25,
        200,
        200,
        40,
        fake_embedder(lambda t: "a" if "Slip" in t else "b"),
    )
    assert [doc[s.char_start : s.char_end] for s in spans] == [
        "Slip days cover lateness. Slip days are limited. Slip days end at cutoff.",
        "Docker runs the stack. Docker uses compose. Docker needs memory.",
    ]


async def test_semantic_group_over_the_cap_is_rechunked_not_truncated():
    doc = " ".join(f"Slip days rule number {i} applies here." for i in range(80))
    spans = await semantic(
        doc, section_of(doc), 25, 60, 50, 10, fake_embedder(lambda t: "a")
    )
    assert len(spans) > 1
    assert all(count_tokens(doc[s.char_start : s.char_end]) <= 60 for s in spans)
    assert spans[0].char_start == 0 and spans[-1].char_end == len(doc)


async def test_semantic_with_under_three_sentences_never_embeds():
    async def no_embed(texts):
        raise AssertionError("must not embed")

    doc = "One sentence. Two sentences."
    assert len(await semantic(doc, section_of(doc), 25, 200, 200, 40, no_embed)) == 1


async def test_chunk_with_skips_heading_only_and_keeps_small_sections_whole():
    async def no_embed(texts):
        raise AssertionError("must not embed")

    cfg = {
        "strategy": "semantic",
        "breakpoint_percentile": 25,
        "max_tokens": 200,
        "overflow": {"chunk_size": 200, "chunk_overlap": 40},
    }
    doc = "## Week 6\n"
    heading_only = Section(0, len(doc), "Week 6", heading_only=True)
    assert await chunk_with(cfg, doc, heading_only, no_embed) == []
    small = "Slip days: 5 per semester. Cutoff: 2 days."
    assert await chunk_with(cfg, small, section_of(small), no_embed) == [
        Span(0, len(small))
    ]


def test_breakpoints_are_relative_to_the_section():
    assert breakpoints([0.9, 0.2, 0.8, 0.85], 25) == [False, True, False, False]
