"""
Unit tests for citation locations, URLs, Text Fragments and labels
(docs/design-rag.md §4.1, §5).

No Docker stack required.

Run with:
    cd tests/unit && pytest test_rag_citations.py -v
"""

from __future__ import annotations

import pytest
from app.services.rag import citations
from app.services.rag.citations import (
    LABEL_MAX,
    LineIndex,
    PageIndex,
    fragment_url,
    markdown_label,
    pdf_label,
    qa_label,
    qa_url,
    quote_path,
    repo_markdown_urls,
    repo_pdf_urls,
    text_fragment,
    upload_source_url,
    viewer_url,
    web_label,
    web_url,
)

WEB = "https://git.doit.wisc.edu/group/proj"
SHA = "a" * 40


def blocks_of(doc: str) -> list[tuple[int, int]]:
    """Block offsets of a document text whose blocks are joined with \\n."""
    out, start = [], 0
    for line in doc.split("\n"):
        out.append((start, start + len(line)))
        start += len(line) + 1
    return out


# --- lines and pages ------------------------------------------------------


def test_line_numbers_treat_char_end_as_exclusive():
    doc = "# Title\nline two\nline three\n"
    index = LineIndex(doc)
    two = doc.index("line two")
    assert index.lines(two, two + len("line two")) == (2, 2)
    assert index.lines(two, two + len("line two\n")) == (2, 2)  # ends on the newline
    assert index.lines(0, len(doc)) == (1, 3)


def test_page_of_offset():
    pages = PageIndex([0, 120, 300])
    assert [pages.page_of(o) for o in (0, 119, 120, 299, 300, 999)] == [
        1,
        1,
        2,
        2,
        3,
        3,
    ]


# --- URLs -----------------------------------------------------------------


@pytest.mark.parametrize("clone", [f"{WEB}.git", f"{WEB}.git/", f"{WEB}/", WEB])
def test_web_url_from_clone_url(clone):
    assert web_url(clone) == WEB


@pytest.mark.parametrize(
    "clone",
    ["https://user:tok@git.doit.wisc.edu/g/p.git", f"{WEB}.git?x=1", f"{WEB}.git#frag"],
)
def test_web_url_rejects_userinfo_query_and_fragment(clone):
    with pytest.raises(ValueError):
        web_url(clone)


def test_eval_paths_survive_percent_encoding_unchanged():
    path = "eval/sample_data/repo/p2-buzzer/instructions.md"
    assert quote_path(path) == path
    assert quote_path("docs/my notes/a#b.md") == "docs/my%20notes/a%23b.md"


def test_repo_urls_pin_the_commit_and_use_the_plain_view():
    citation, source = repo_markdown_urls(WEB, SHA, "p2-buzzer/instructions.md", 10, 25)
    assert source == f"{WEB}/-/blob/{SHA}/p2-buzzer/instructions.md"
    assert citation == f"{source}?plain=1#L10-25"
    citation, source = repo_pdf_urls(WEB, SHA, "lecture-10/slides.pdf", 4)
    assert (source, citation) == (
        f"{WEB}/-/raw/{SHA}/lecture-10/slides.pdf",
        f"{WEB}/-/raw/{SHA}/lecture-10/slides.pdf#page=4",
    )


def test_upload_urls_contain_the_stored_path():
    path = "eval/sample_data/repo/p2-buzzer/instructions.md"
    source = upload_source_url(1, 3, path)
    assert source == f"/api/courses/1/resources/3/files/{path}"
    assert path in source  # the harness's substring check (§5.5)
    assert (
        viewer_url(3, path, "lines=10-25") == f"/student/sources/3/{path}?lines=10-25"
    )
    assert qa_url(7) == "/student/questions/7"


# --- Text Fragments -------------------------------------------------------

CARDS = "\n".join(
    [
        "Course Schedule",
        "Wed: P2 Released (Sep 16)",
        "Team project: 2–4 students",
        "Wed: P3 Released (Oct 07)",
        "Due: Tuesday, October 27 at 11:59 PM",
        "Team project: 2–4 students",
    ]
)


def span_of(doc: str, text: str, nth: int = 0) -> tuple[int, int]:
    start = -1
    for _ in range(nth + 1):
        start = doc.index(text, start + 1)
    return start, start + len(text)


def test_short_single_block_span_is_quoted_whole():
    a, b = span_of(CARDS, "Due: Tuesday, October 27 at 11:59 PM")
    assert text_fragment(CARDS, blocks_of(CARDS), a, b) == (
        "Due: Tuesday, October 27 at 11:59 PM",
        None,
    )


def test_long_single_block_span_uses_start_and_end_terms():
    doc = " ".join(f"w{i}" for i in range(30))
    start, end = text_fragment(doc, blocks_of(doc), 0, len(doc))
    assert (start, end) == ("w0 w1 w2 w3 w4 w5", "w24 w25 w26 w27 w28 w29")


def test_span_across_blocks_takes_terms_from_first_and_last_block():
    a, _ = span_of(CARDS, "Wed: P3 Released")
    _, b = span_of(CARDS, "Due: Tuesday, October 27 at 11:59 PM")
    assert text_fragment(CARDS, blocks_of(CARDS), a, b) == (
        "Wed: P3 Released (Oct 07)",
        "Tuesday, October 27 at 11:59 PM",
    )


def test_repeated_text_is_anchored_at_the_section_heading():
    a, b = span_of(CARDS, "Team project: 2–4 students", nth=1)
    heading = span_of(CARDS, "Wed: P3 Released (Oct 07)")
    assert text_fragment(CARDS, blocks_of(CARDS), a, b, heading_block=heading) == (
        "Wed: P3 Released (Oct 07)",
        "Team project: 2–4 students",
    )


def test_fragment_terms_encode_dash_comma_and_ampersand():
    url = fragment_url("https://x.edu/s.html", "Q&A - week 1, part 2", "end")
    assert (
        url == "https://x.edu/s.html#:~:text=Q%26A%20%2D%20week%201%2C%20part%202,end"
    )
    assert fragment_url("https://x.edu/s.html", "only", None).endswith("#:~:text=only")


# --- labels ---------------------------------------------------------------


def test_label_templates():
    assert (
        web_label("Schedule", "Course Schedule › Week 6")
        == "Schedule › Course Schedule › Week 6"
    )
    assert (
        markdown_label("Course repository", "p2-buzzer/instructions.md", 10, 25)
        == "Course repository: p2-buzzer/instructions.md, lines 10–25"
    )
    assert pdf_label("Course repository", "lecture-10/slides.pdf", 4) == (
        "Course repository: lecture-10/slides.pdf, page 4"
    )
    assert (
        qa_label("How do I reset my migrations?")
        == "Q&A: How do I reset my migrations?"
    )


def test_long_labels_are_cut_in_the_middle_and_keep_both_ends():
    path = "/".join(f"folder-{i}" for i in range(60)) + "/notes.md"
    label = markdown_label("Course repository", path, 10, 25)
    assert len(label) == LABEL_MAX
    assert label.startswith("Course repository: folder-0/")
    assert label.endswith("notes.md, lines 10–25")
    assert "…" in label


# ---------------------------------------------------------------------------
# citations_for: what a posted AI answer cites (§6.4)
# ---------------------------------------------------------------------------


def _chunk(url, sim, **meta):
    from types import SimpleNamespace

    return SimpleNamespace(
        text="t" * 900,
        similarity=sim,
        metadata={"citation_url": url, "label": "L", "resource_id": 3, **meta},
    )


def test_citations_drop_repeated_urls_and_renumber_ranks():
    cites = citations.citations_for(
        [
            _chunk("/a", 0.9, resource_type="repo_pdf", page=2),
            _chunk("/a", 0.8, resource_type="repo_pdf", page=2),
            _chunk("/b", 0.7, resource_type="qa_thread", question_id=7),
        ]
    )
    assert [c["rank"] for c in cites] == [1, 2]
    assert [c["citation_url"] for c in cites] == ["/a", "/b"]
    assert cites[0]["location_json"] == {"page": 2}
    assert cites[1]["location_json"] == {"question_id": 7}
    assert len(cites[0]["quoted_text"]) == citations.QUOTED_TEXT_CHARS


def test_citation_locations_per_type():
    md = citations.location(
        {"resource_type": "repo_markdown", "line_start": 4, "line_end": 9}
    )
    assert md == {"lines": [4, 9]}
    web = citations.location(
        {
            "resource_type": "syllabus",
            "text_start": "Late Policy",
            "text_end": "any project",
            "char_start": 10,
            "char_end": 90,
        }
    )
    assert web == {
        "text_start": "Late Policy",
        "text_end": "any project",
        "chars": [10, 90],
    }
