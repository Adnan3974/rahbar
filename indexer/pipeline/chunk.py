"""Stage 3: Chunk. Structure-aware, with overlap."""

from __future__ import annotations

import re
from .models import Chunk, Document


def _approx_tokens(text: str) -> int:
    """Approximate tokens based on whitespace-delimited words (1 token ~ 0.75 words, so ~1.3 tokens/word)."""
    words = text.split()
    return max(1, int(len(words) * 1.3))


def _split_into_sentences(text: str) -> list[str]:
    """Split paragraph text into sentences preserving sentence boundaries."""
    raw_sentences = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in raw_sentences if s.strip()]


def _split_into_paragraphs(section_text: str) -> list[str]:
    """Split section text into natural paragraphs."""
    paras = re.split(r"\n\s*\n+", section_text)
    return [p.strip() for p in paras if p.strip()]


def chunk(doc: Document, size: int, overlap: int) -> list[Chunk]:
    """Structure-aware chunking with sliding overlap.

    Splits along section/clause headings first, then paragraphs, then sentences.
    Preserves section metadata, page number, doc_version, and superseded flags.
    """
    chunks: list[Chunk] = []
    chunk_idx = 0

    # Section heading regex: Markdown # headings or numbered clauses like "1.21 Attendance"
    heading_pattern = re.compile(
        r"^(#{1,4}\s+.+|(?:\d+(?:\.\d+)*)\s+[A-Z][\w\s,–—\-]{2,80})$", re.M
    )

    for page in doc.pages:
        page_text = page.text
        if not page_text.strip():
            continue

        # Find heading boundaries within the page
        matches = list(heading_pattern.finditer(page_text))
        sections: list[tuple[str, str]] = []

        if not matches:
            # Entire page under default section
            sections.append((f"{doc.source} (Page {page.page})", page_text))
        else:
            # Text before the first heading
            if matches[0].start() > 0:
                pre = page_text[: matches[0].start()].strip()
                if pre:
                    sections.append((f"{doc.source} (Page {page.page})", pre))

            for i, m in enumerate(matches):
                heading = m.group(0).lstrip("#").strip()
                start = m.end()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(page_text)
                body = page_text[start:end].strip()
                content = f"{heading}\n{body}" if body else heading
                sections.append((heading, content))

        # Now subdivide each section into chunks fitting target size with overlap
        for heading, sec_text in sections:
            paragraphs = _split_into_paragraphs(sec_text)
            current_sentences: list[str] = []
            current_tokens = 0

            for para in paragraphs:
                sentences = _split_into_sentences(para)
                for sentence in sentences:
                    s_tokens = _approx_tokens(sentence)
                    if current_tokens + s_tokens > size and current_sentences:
                        # Flush current chunk
                        chunk_text = " ".join(current_sentences)
                        chunk_id = f"{doc.source}:p{page.page}:c{chunk_idx:04d}"
                        chunks.append(
                            Chunk(
                                id=chunk_id,
                                text=chunk_text,
                                source=doc.source,
                                section=heading,
                                page=page.page,
                                doc_version=doc.doc_version,
                                superseded=doc.superseded,
                            )
                        )
                        chunk_idx += 1

                        # Keep overlap tokens for the next chunk
                        overlap_sentences: list[str] = []
                        overlap_tokens = 0
                        for prev_s in reversed(current_sentences):
                            prev_t = _approx_tokens(prev_s)
                            if overlap_tokens + prev_t <= overlap:
                                overlap_sentences.insert(0, prev_s)
                                overlap_tokens += prev_t
                            else:
                                break
                        current_sentences = overlap_sentences
                        current_tokens = overlap_tokens

                    current_sentences.append(sentence)
                    current_tokens += s_tokens

            if current_sentences:
                chunk_text = " ".join(current_sentences)
                chunk_id = f"{doc.source}:p{page.page}:c{chunk_idx:04d}"
                chunks.append(
                    Chunk(
                        id=chunk_id,
                        text=chunk_text,
                        source=doc.source,
                        section=heading,
                        page=page.page,
                        doc_version=doc.doc_version,
                        superseded=doc.superseded,
                    )
                )
                chunk_idx += 1

    return chunks
