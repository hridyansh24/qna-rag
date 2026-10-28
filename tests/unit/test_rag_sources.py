"""
Unit tests for the structural splitters: HTML cleaning and sections, markdown
sections, PDF pages (docs/design-rag.md §5.1–§5.3, §13).

No Docker stack required.

Run with:
    cd tests/unit && pytest test_rag_sources.py -v
"""

from __future__ import annotations

import io
import itertools
import pathlib

import pytest
from app.services.rag.citations import LineIndex
from app.services.rag.sources import markdown, pdf, web
from pypdf import PdfReader, PdfWriter

SAMPLE = pathlib.Path(__file__).parents[2] / "eval" / "sample_data"


def blocks(html: str | bytes) -> list[str]:
    doc = web.clean_html(html)
    return [doc.text[b.start : b.end] for b in doc.blocks]


# --- HTML cleaning ----------------------------------------------------------


@pytest.fixture(scope="module")
def schedule() -> web.WebDocument:
    return web.clean_html((SAMPLE / "web" / "schedule.html").read_bytes())


def test_schedule_p3_card_blocks(schedule):
    texts = [schedule.text[b.start : b.end] for b in schedule.blocks]
    i = texts.index("Wed: P3 Released (Oct 07)")
    assert texts[i : i + 5] == [
        "Wed: P3 Released (Oct 07)",
        "🚀 Released: P3 — RAG-Based Smart Q&A Application (opens in new tab)",
        "Due: Tuesday, October 27 at 11:59 PM",  # answers q04
        (
            "Full stack + local AI models via Ollama (generation) and Infinity "
            "(embeddings), RAG pipeline, vector embeddings"
        ),
        "Team project: 2 students",
    ]


def test_blocks_are_joined_with_newlines_at_their_offsets(schedule):
    assert "\n".join(schedule.text[b.start : b.end] for b in schedule.blocks) == (
        schedule.text
    )
    assert schedule.title == "AI-Assisted Software Development"


def test_removed_elements_and_hidden_text_are_dropped():
    html = """<html><head><title>T</title><style>p{}</style></head><body>
      <header>Site header</header><nav>Menu</nav>
      <p>Kept</p><script>var x = 1;</script>
      <div hidden>Hidden attr</div><div style="color:red; DISPLAY: none">Hidden style</div>
      <footer>Footer</footer></body></html>"""
    assert blocks(html) == ["Kept"]


def test_bare_div_text_survives_and_inline_text_joins():
    assert blocks("<div>bare <span>inline</span> text<p>para</p>tail</div>") == [
        "bare inline text",
        "para",
        "tail",
    ]


def test_unclosed_list_items_collect_each_text_once():
    texts = blocks("<ul><li>one<li>two<li>three</ul><p>after")
    assert texts == ["one", "two", "three", "after"]


def test_br_splits_blocks_and_whitespace_collapses():
    assert blocks("<p><b>Due</b>:   Tuesday<br>\n  Late:\tnone</p>") == [
        "Due: Tuesday",
        "Late: none",
    ]


def test_pre_keeps_spacing_one_block_per_line():
    assert blocks("<pre>a = 1\n    b = 2\n\n</pre>") == ["a = 1", "    b = 2"]


def test_entities_are_decoded():
    assert blocks("<p>P3 &mdash; Q&amp;A</p>") == ["P3 — Q&A"]


# --- web sections -------------------------------------------------------------


def test_sections_are_disjoint_ordered_and_cover_every_block(schedule):
    sections = web.split_sections(schedule)
    covered = []
    for a, b in itertools.pairwise(sections):
        assert a.char_end < b.char_start
    for s in sections:
        covered += [
            blk for blk in schedule.blocks if s.char_start <= blk.start < s.char_end
        ]
    assert covered == schedule.blocks


def test_heading_paths_and_heading_only_sections(schedule):
    sections = {s.path: s for s in web.split_sections(schedule)}
    p3 = sections["Course Schedule › Week 6 › Wed: P3 Released (Oct 07)"]
    assert not p3.heading_only
    assert schedule.text[p3.heading[0] : p3.heading[1]] == "Wed: P3 Released (Oct 07)"
    assert sections["Course Schedule › Week 6"].heading_only  # h2 followed by an h3


def test_text_before_first_heading_takes_the_title():
    doc = web.clean_html(
        "<title>Page</title><p>Intro</p><h2>A</h2><p>x</p><h3>B</h3><p>y</p><h2>C</h2><p>z</p>"
    )
    assert [s.path for s in web.split_sections(doc)] == ["Page", "A", "A › B", "C"]


# --- markdown -----------------------------------------------------------------


def test_markdown_text_normalizes_line_endings_and_bom():
    assert markdown.markdown_text(b"\xef\xbb\xbf# T\r\nx\ry\n") == "# T\nx\ny\n"
    with pytest.raises(UnicodeDecodeError):
        markdown.markdown_text(b"caf\xe9")


MD = """Intro line
# Title
## Setup
Run this:
```bash
# not a heading
make
```
##### Small heading is content
## Empty

### Deep
text
"""


def test_markdown_sections_ignore_fenced_headings_and_cover_the_text():
    sections = markdown.split_markdown(MD, "notes.md")
    assert [s.path for s in sections] == [
        "notes.md",
        "Title",
        "Title › Setup",
        "Title › Empty",
        "Title › Empty › Deep",
    ]
    assert [s.heading_only for s in sections] == [False, True, False, True, False]
    assert sections[0].char_start == 0 and sections[-1].char_end == len(MD)
    for a, b in itertools.pairwise(sections):
        assert a.char_end == b.char_start


def test_markdown_line_numbers_match_the_file():
    text = markdown.markdown_text(MD.replace("\n", "\r\n").encode())
    deep = markdown.split_markdown(text, "notes.md")[-1]
    assert LineIndex(text).lines(deep.char_start, deep.char_end) == (12, 13)


# --- PDF ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def slides_bytes() -> bytes:
    return (SAMPLE / "repo" / "lecture-10" / "slides.pdf").read_bytes()


def test_pdf_pages_and_offset_table(slides_bytes):
    doc = pdf.pdf_document(slides_bytes)
    pages = pdf.split_pages(doc)
    reader = PdfReader(io.BytesIO(slides_bytes))
    assert len(pages) == len(reader.pages) == len(doc.page_starts)
    for n, section in enumerate(pages):
        assert section.char_start == doc.page_starts[n]
        expected = (reader.pages[n].extract_text() or "").replace("\r\n", "\n")
        assert doc.text[section.char_start : section.char_end] == expected
    assert pages[-1].char_end == len(doc.text)


def test_encrypted_and_corrupt_pdfs_are_unreadable(slides_bytes):
    writer = PdfWriter(clone_from=io.BytesIO(slides_bytes))
    writer.encrypt(user_password="secret", algorithm="RC4-128")
    out = io.BytesIO()
    writer.write(out)
    with pytest.raises(pdf.UnreadablePdf, match="encrypted"):
        pdf.pdf_document(out.getvalue())
    with pytest.raises(pdf.UnreadablePdf):
        pdf.pdf_document(b"%PDF-1.4 this is not a pdf")
