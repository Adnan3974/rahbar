"""Stage 2: Clean. Remove artefacts without destroying structure."""

from __future__ import annotations

import re
from collections import Counter

from .models import Document, Page


def clean(doc: Document) -> Document:
    """Strip headers and footers that repeat on every page; keep headings and
    section boundaries, because chunking and citations depend on them.
    """
    if not doc.pages:
        return doc

    # Identify lines that repeat across more than 40% of pages (likely headers/footers)
    line_counts: Counter[str] = Counter()
    for page in doc.pages:
        unique_lines_in_page = {line.strip() for line in page.text.splitlines() if line.strip()}
        for line in unique_lines_in_page:
            # Do not flag numbered clauses, section headings or short table headers
            if re.match(r"^(\d+(\.\d+)*)\s+[A-Z]", line) or line.startswith("#"):
                continue
            line_counts[line] += 1

    total_pages = len(doc.pages)
    threshold = max(2, int(total_pages * 0.40))
    repeating_artifacts = {
        line for line, count in line_counts.items()
        if count >= threshold and len(line) > 3
    }

    cleaned_pages: list[Page] = []
    for page in doc.pages:
        lines = page.text.splitlines()
        filtered_lines = []
        for line in lines:
            stripped = line.strip()
            # Omit detected header/footer lines and standalone page numbering like "Page 12 of 60"
            if stripped in repeating_artifacts:
                continue
            if re.match(r"^(Page\s+\d+(\s+of\s+\d+)?|\d+\s*/\s*\d+|\b\d+\b)$", stripped, re.I):
                continue
            filtered_lines.append(line)

        text = "\n".join(filtered_lines)
        # Normalize non-breaking spaces and excessive consecutive newlines (>3)
        text = text.replace("\u00a0", " ")
        text = re.sub(r"\n{3,}", "\n\n", text)
        cleaned_pages.append(Page(source=page.source, page=page.page, text=text.strip(), ocr=page.ocr))

    return Document(
        source=doc.source,
        doc_version=doc.doc_version,
        superseded=doc.superseded,
        pages=cleaned_pages,
    )
