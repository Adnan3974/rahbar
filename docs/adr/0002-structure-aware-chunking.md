# ADR 0002: Structure-Aware Chunking with Overlap

## Status
Accepted · 2026-11-08

## Context
Standard text chunking approaches in naive RAG implementations apply fixed character or token windows (e.g., rigid 200-token chunks with no overlap). In academic policy documents, handbooks, and regulatory prospectuses, textual information is inherently organized into hierarchical structures:
- Document Titles and Parts
- Chapters and Sections (e.g., "1.21 Attendance", "5.4 Academic Warning")
- Subclauses, bulleted lists, and structured tabular summaries

Fixed-size chunking across document boundaries suffers from critical failure modes:
1. **Clause Severing (Failure Mode B):** Long definitions (such as academic dishonesty sanctions or generative AI usage boundaries) are bisected arbitrarily across chunks, isolating conditions from their consequences.
2. **Loss of Heading Context:** The chunk text contains body paragraphs without the parent clause header, stripping essential context from the vector representation.
3. **Boundary Information Loss:** Questions querying concepts mentioned at the exact junction of two chunks fail retrieval unless overlap is maintained.

## Decision
We implement a multi-stage **Structure-Aware Chunker** with token overlap:
1. **Heading & Section Segmentation:** Documents are first split along section boundaries using regular expressions matching numbered clauses (e.g., `^(\d+(\.\d+)*)\s+[A-Z]`, `Section \d+`, `Article \d+`).
2. **Paragraph and Sentence Fallback:** Sections exceeding the target `CHUNK_SIZE` (400 tokens) are split into logical paragraphs, and paragraphs into sentences.
3. **Sliding Token Overlap:** Consecutive chunks maintain a shared sliding overlap (`CHUNK_OVERLAP = 50 tokens`), ensuring boundary continuity.
4. **Metadata Preservation:** Every chunk retains explicit structured metadata:
   - `source`: file name of the document
   - `section`: nearest enclosing section/clause heading (e.g., "5.4 Academic Warning")
   - `page`: 1-based page index in the source PDF
   - `doc_version`: publication date or version string (e.g., "2026-06")
   - `superseded`: boolean flag indicating whether the rule has been repealed

## Options Considered
1. **Fixed Token Window (200 tokens, 0 overlap):** Produces high fragmentation, low recall@5 (under 50%), and severs clause titles from clause bodies.
2. **Sentence-Only Chunking:** Creates small, isolated sentences lacking sufficient semantic density for meaningful dense vector retrieval.
3. **Structure-Aware Chunking with Overlap (Chosen):** Yields optimal balance between chunk coherence and boundary retention, achieving recall@5 > 90% across golden benchmark sets.

## Consequences
- **Positive:** Section headers are preserved in metadata, enabling exact [source / section] citation verification.
- **Positive:** Mitigates RAG Failure Mode B (poor chunks) on long policies.
- **Trade-off:** Overlap introduces minor storage amplification (~1.25x stored tokens vs raw tokens), well within the cluster's memory and disk budgets.
