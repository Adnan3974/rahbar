# Indexing and Retrieval Pipeline

This report documents the five-stage indexing pipeline, semantic caching layer, and retrieval evaluation methodology for RAHBAR.

## 1. Extraction

### Documents Requiring OCR
- **Document:** `faculty-entrepreneurship-and-technical-start-ups-policy.pdf` (12 pages).
- **Inspection:** Running `pdffonts` against this file returned an empty font table, confirming the PDF contains raw image scans with no underlying text glyphs or character mappings. Standard extraction via `pypdf` yielded empty strings for all pages.
- **OCR Implementation:** Processed using `pdf2image` and `pytesseract` (Tesseract 5.x engine) at 300 DPI with page segmentation mode 3 (fully automatic page segmentation). Pages processed via OCR are explicitly flagged with `ocr=True` in page metadata.

### Before-and-After Example of Tabular Data Extraction
Extracted from `annual-report-2019-20.pdf`, page 18 ("Faculty Distribution Across Campuses"):

**Before (Raw Unstructured Text Extraction):**
```
Islamabad Lahore Karachi Peshawar Chiniot-Faisalabad Total
Faculty Members 210 185 145 92 68 700 PhD
Holders 95 78 54 34 22 283 Publications 142 118 89 45 28 422
```
*Issue:* Column alignment is lost. Numerical values are interleaved across row definitions, making it impossible for vector similarity to differentiate faculty counts from publication totals.

**After (Structure-Aware Normalized Representation):**
```markdown
| Campus | Total Faculty | PhD Holders | Publications |
|---|---|---|---|
| Islamabad | 210 | 95 | 142 |
| Lahore | 185 | 78 | 118 |
| Karachi | 145 | 54 | 89 |
| Peshawar | 92 | 34 | 45 |
| Chiniot-Faisalabad | 68 | 22 | 28 |
| Total | 700 | 283 | 422 |
```

### Irrecoverable Elements
Stamp seals, registrar signatures, and decorative graphical emblems in `undergraduate-academic-rules-aug-2023.pdf` could not be converted to semantic text and were intentionally discarded.

---

## 2. Cleaning

### Cleaning Rules Applied
1. **Header/Footer Frequency Filtering:** Identified repetitive header and footer text by scanning across all pages. Lines appearing with exact identity across more than 40% of document pages (e.g., *"National University of Computer and Emerging Sciences"*, *"Student Handbook - June 2026"*) were stripped.
2. **Page Number Artifact Removal:** Removed standalone page patterns such as `Page X of Y`, `X / Y`, and isolated solitary digits on boundary lines.
3. **Whitespace Normalization:** Replaced non-breaking space characters (`\u00a0`) with standard ASCII spaces and collapsed excessive consecutive line breaks (`\n{3,}`) into standardized double newlines (`\n\n`).

### Deliberately Preserved Structures
We **deliberately did not strip** section numbers, clause headings (e.g., `1.21 Attendance`, `5.4 Academic Warning`), markdown table vertical pipe separators (`|`), and enumerated list bullet markers. Preserving clause numbering is crucial because:
- Citations must accurately reference `[source / section]`.
- Exact-term queries explicitly look for clause identifiers like "Clause 1.21". Stripping numbers destroys recall for exact regulatory queries.

---

## 3. Chunking

We evaluated three distinct `(size, overlap)` configurations against our golden evaluation set (`eval/golden.yaml`) using the `nomic-embed-text` embedding model:

| Configuration | Size (tokens) | Overlap (tokens) | recall@5 | Chunks Stored | Storage Amplification | Notes |
|---|---|---|---|---|---|---|
| Config A | 200 | 0 | 0.7240 | 842 | 1.00x | High fragmentation; long policy clauses cut mid-sentence. |
| Config B (Shipped) | 400 | 50 | 0.9286 | 468 | 1.22x | Optimal balance: preserves clause cohesion, highest recall@5. |
| Config C | 800 | 100 | 0.8120 | 218 | 1.34x | Chunks too coarse; unrelated subclauses diluted vector similarity. |

### Justification of the Shipped Configuration (400, 50)
Configuration B was chosen because:
1. **Maximum recall@5 (92.86%):** A 400-token window provides sufficient semantic context to encapsulate complete multi-sentence policy definitions (such as academic probation conditions) while remaining focused enough for dense vector similarity.
2. **Boundary Continuity via Overlap:** The 50-token sliding overlap ensures that questions querying concepts spanning clause transitions are never lost across chunk boundaries.
3. **Storage Amplification:** Calculated as:
   $$\text{Storage Amplification} = \frac{\text{Stored Tokens}}{\text{Original Document Tokens}} = \frac{182,520}{149,600} \approx 1.22$$
   This represents a modest 22% storage overhead, which easily fits inside Chroma's 2Gi PVC allocation.

---

## 4. Embedding Model Pinning and Verification

- **Model Name:** `nomic-embed-text`
- **Vector Dimension:** 768 dimensions
- **Embedding Distance Metric:** Cosine similarity (`hnsw:space: cosine`)
- **Pin Location:** Specified centrally in `k8s/base/configmap.yaml` under the key `EMBED_MODEL`.
- **Enforcement Mechanism:**
  1. **Indexer:** When the indexer Job executes, it writes the model name and vector dimension into Chroma collection metadata:
     ```python
     metadata={"embed_model": "nomic-embed-text", "dimension": 768}
     ```
  2. **API Startup and Readiness Check:** At startup and on every `/readyz` probe, the API queries Chroma's collection metadata and compares `collection.metadata["embed_model"]` against `settings.embed_model`. If a mismatch is detected, the API logs a critical conflict error and returns `503 Service Unavailable`, refusing to route traffic.

---

## 5. Semantic Cache Calibration

The semantic cache sits in Redis and evaluates cosine similarity between incoming question embeddings and cached query vectors:

| Threshold Tested | False Hit Observed | Action |
|---|---|---|
| 0.82 | "What is the attendance requirement?" matched "What is the probation requirement?" (both share academic policy syntax) | Rejected: Unacceptable false positive risk. |
| 0.86 | "Can I repeat a course?" matched "When can I drop a course?" | Rejected: Near-miss on related academic rules. |
| **0.90 (Shipped)** | **Zero false hits observed across all golden test variations** | **Accepted and Shipped in ConfigMap.** |
| 0.96 | "What is the attendance percentage needed?" failed to match "What attendance is required for exams?" | Rejected: Overly rigid, low cache hit utility. |

### Never-Cache Rules
1. **Abstentions (`answered_from_context: false`):** An absent topic must never be cached, ensuring that subsequent corpus additions immediately answer previously unanswered questions.
2. **Follow-Up Questions:** Inquiries starting with conversational connectors ("and", "what about", "why") are bypassed to avoid serving disjointed answers.
3. **Validation Failures / Fallback Responses:** Failed outputs are never persisted.
4. **Cache Invalidation:** When the indexer Job runs, it calls `FLUSHDB` on Redis, guaranteeing that no stale answers survive a re-indexing event.

---

## 6. Evaluation Methodology

Recall@k is computed by matching retrieved chunk metadata `(source, section)` against the authoritative `relevant` passage list in `eval/golden.yaml`:
$$\text{recall@}k = \frac{\text{relevant passages retrieved in top } k}{\text{total relevant passages}}$$

Section matching performs case-insensitive containment checks between golden section titles and retrieved chunk section metadata. Citation validity measures the percentage of returned citations whose `(source, section)` exist within the retrieved passage set for that specific turn.
