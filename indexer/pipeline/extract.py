"""Stage 1: Extract. PDF (or HTML, or Markdown) to text, page by page."""

from __future__ import annotations

import logging
import re
from html.parser import HTMLParser
from pathlib import Path

from .models import Document, Page

log = logging.getLogger("rahbar.indexer.extract")


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._pieces: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self._pieces.append(data.strip())

    def get_text(self) -> str:
        return "\n".join(self._pieces)


def _ocr_page(pdf_path: str, page_num: int) -> str:
    """Attempt OCR using pdf2image and pytesseract; fallback gracefully if binaries are absent."""
    try:
        from pdf2image import convert_from_path
        import pytesseract

        images = convert_from_path(pdf_path, first_page=page_num, last_page=page_num)
        if images:
            text = pytesseract.image_to_string(images[0])
            return text.strip()
    except Exception as exc:
        log.warning("OCR failed or tesseract/poppler not installed on system",
                    extra={"page": page_num, "error": str(exc)})
    return "[Scanned document: text layer unavailable via OCR]"


def _extract_pdf(path: str, doc_version: str, superseded: bool) -> Document:
    pages: list[Page] = []
    source = Path(path).name

    # Try extraction using pypdf first for fast parsing
    import pypdf

    try:
        reader = pypdf.PdfReader(path)
        for i, pdf_page in enumerate(reader.pages, start=1):
            text = pdf_page.extract_text() or ""
            is_ocr = False
            if len(text.strip()) < 20:
                # Page has no text layer or is scanned
                ocr_text = _ocr_page(path, i)
                if ocr_text and ocr_text != "[Scanned document: text layer unavailable via OCR]":
                    text = ocr_text
                    is_ocr = True
                else:
                    text = f"[Page {i}: Scanned document content without native text layer]"
                    is_ocr = True
            pages.append(Page(source=source, page=i, text=text, ocr=is_ocr))
    except Exception as exc:
        log.error("pypdf failed, attempting pdfplumber fallback", extra={"error": str(exc)})
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            for i, plumb_page in enumerate(pdf.pages, start=1):
                text = plumb_page.extract_text() or ""
                is_ocr = len(text.strip()) < 20
                if is_ocr:
                    text = _ocr_page(path, i)
                pages.append(Page(source=source, page=i, text=text, ocr=is_ocr))

    return Document(source=source, doc_version=doc_version, superseded=superseded, pages=pages)


def _extract_html(path: str, doc_version: str, superseded: bool) -> Document:
    source = Path(path).name
    raw = Path(path).read_text(encoding="utf-8", errors="replace")
    parser = _HTMLTextExtractor()
    parser.feed(raw)
    text = parser.get_text()
    return Document(
        source=source,
        doc_version=doc_version,
        superseded=superseded,
        pages=[Page(source=source, page=1, text=text, ocr=False)],
    )


def _extract_text_or_md(path: str, doc_version: str, superseded: bool) -> Document:
    source = Path(path).name
    raw = Path(path).read_text(encoding="utf-8", errors="replace")
    # Strip YAML front matter if present
    content = re.sub(r"^---[\s\S]*?---\n", "", raw)
    return Document(
        source=source,
        doc_version=doc_version,
        superseded=superseded,
        pages=[Page(source=source, page=1, text=content, ocr=False)],
    )


def extract(path: str, doc_version: str, superseded: bool) -> Document:
    """Return the document's text page by page.

    Detect pages with no text layer and OCR them; mark those pages ocr=True.
    Supports PDF, HTML, Markdown, and plain text files.
    """
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        return _extract_pdf(path, doc_version, superseded)
    if ext in (".html", ".htm"):
        return _extract_html(path, doc_version, superseded)
    return _extract_text_or_md(path, doc_version, superseded)
