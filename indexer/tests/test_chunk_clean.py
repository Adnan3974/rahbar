"""Tests for indexer extraction, cleaning, and structure-aware chunking."""

from __future__ import annotations

from pipeline.clean import clean
from pipeline.chunk import chunk
from pipeline.models import Document, Page


def test_cleaner_removes_repeating_headers_and_preserves_headings() -> None:
    doc = Document(
        source="test-handbook.pdf",
        doc_version="2026-06",
        superseded=False,
        pages=[
            Page(source="test-handbook.pdf", page=1, text="FAST National University\n1.21 Attendance\nPage 1 of 3\nStudents must attend 80% of classes."),
            Page(source="test-handbook.pdf", page=2, text="FAST National University\n5.4 Academic Warning\nPage 2 of 3\nA CGPA below 2.00 triggers warning."),
            Page(source="test-handbook.pdf", page=3, text="FAST National University\nConclusion\nPage 3 of 3\nEnd of rules."),
        ]
    )
    cleaned = clean(doc)
    assert len(cleaned.pages) == 3
    # Check that "FAST National University" repeating header is stripped
    for p in cleaned.pages:
        assert "FAST National University" not in p.text
        assert "Page " not in p.text
    # Check that section headings are preserved
    assert "1.21 Attendance" in cleaned.pages[0].text
    assert "5.4 Academic Warning" in cleaned.pages[1].text


def test_structure_aware_chunking_with_overlap() -> None:
    doc = Document(
        source="handbook.pdf",
        doc_version="2026-06",
        superseded=False,
        pages=[
            Page(
                source="handbook.pdf",
                page=1,
                text="1.21 Attendance Policy\n" + ("Attendance is mandatory. " * 50) +
                     "\n5.4 Academic Warning\n" + ("A warning is issued for low CGPA. " * 50)
            )
        ]
    )
    chunks = chunk(doc, size=100, overlap=20)
    assert len(chunks) > 1
    # Verify metadata fields are preserved
    for c in chunks:
        assert c.source == "handbook.pdf"
        assert c.page == 1
        assert c.doc_version == "2026-06"
        assert c.superseded is False
        assert c.section in ["1.21 Attendance Policy", "5.4 Academic Warning"]
