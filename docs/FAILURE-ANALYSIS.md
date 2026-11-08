# Failure Analysis

To evaluate system resilience, observability, and diagnostic procedures, we intentionally induced failures across four pipeline stages, recorded observable symptoms, traced the root causes through metrics and logs, and verified the corresponding remedies.

---

## Stage A · Extraction: Scanned PDF Indexed Without OCR

- **What we broke:** We disabled the OCR fallback in `indexer/pipeline/extract.py` and processed `faculty-entrepreneurship-and-technical-start-ups-policy.pdf` using naive text extraction only. Because the PDF consists of raw scanned bitmap pages, all pages produced empty strings.
- **Symptom:** Queries regarding startup equity shares, IP ownership, and faculty incubation returned empty retrievals. The system answered with an honest abstention (`answered_from_context: false`, `confidence: "low"`), even though the relevant document exists in the corpus directory.
- **Diagnosis (as if not caused on purpose):**
  1. Inspecting the indexer logs showed:
     `{"msg": "chunked", "source": "faculty-entrepreneurship-and-technical-start-ups-policy.pdf", "chunks": 0}`
  2. Inspecting the source PDF with `pdffonts corpus/raw/faculty-entrepreneurship-and-technical-start-ups-policy.pdf` revealed an empty font table, confirming the file lacks a digital text layer.
  3. Retrieval logs showed similarity scores for questions regarding faculty startups never exceeded `0.32`, well below `RELEVANCE_FLOOR = 0.65`.
- **Remedy:** Re-enabled Tesseract OCR with `pdf2image` in `extract.py`. Re-running the indexer Job generated 24 text chunks from the scanned policy with `ocr=True` metadata, restoring full retrieval recall.

---

## Stage B · Chunking: Fixed-Size 100-Token Chunks Without Overlap

- **What we broke:** In `indexer/pipeline/chunk.py`, we replaced structure-aware section splitting with rigid 100-token fixed windows and zero token overlap (`size=100`, `overlap=0`).
- **Symptom:** Recall@5 dropped precipitously on multi-clause policy questions, falling from `92.86%` to `61.40%`. The CI evaluation gate failed with a `MAX_RECALL5_DROP` violation. Answers frequently quoted incomplete regulatory clauses without parent section headers.
- **Diagnosis (as if not caused on purpose):**
  1. Automated test suite reported:
     `GATE FAILED: recall@5 dropped by 31.46%, exceeding max allowed drop of 5%`
  2. Examining retrieved passages in the API logs:
     `{"chunk_id": "handbook:p12:c0032", "text": "shall be liable to a penalty under section", "section": "unknown"}`
     The clause condition was severed from the penalty clause, and the section heading was completely absent from metadata.
- **Remedy:** Restored structure-aware hierarchical chunking (`size=400`, `overlap=50`) that preserves numbered clause headings (`1.21 Attendance`, `5.4 Academic Warning`) and retains 50 sliding tokens across boundaries.

---

## Stage C · Retrieval: Incompatible Embedding Model on API

- **What we broke:** We altered `EMBED_MODEL` in the API's configuration to `all-MiniLM-L6-v2` while leaving the Chroma index populated with `nomic-embed-text` vectors.
- **Symptom:** The API pod failed its readiness probe and sat at `0/1 READY` in `kubectl get pods`, preventing any corrupted traffic from reaching users.
- **Diagnosis (as if not caused on purpose):**
  1. Executing `kubectl describe pod api-xxxx -n rahbar` revealed:
     `Readiness probe failed: HTTP probe failed with statuscode: 503`
  2. Examining container stdout via `kubectl logs api-xxxx -n rahbar`:
     ```json
     {"logger": "rahbar.api", "level": "ERROR", "msg": "guardrail triggered: embedding model mismatch: collection was indexed with 'nomic-embed-text' but API EMBED_MODEL is 'all-MiniLM-L6-v2'"}
     ```
  3. The guardrail in `health.py` and `main.py` successfully blocked silent failure, making the broken state completely unreachable.
- **Remedy:** Realigned `EMBED_MODEL` in `k8s/base/configmap.yaml` to `nomic-embed-text` and restarted the pod. The API verified metadata parity and returned `HTTP 200` on `/readyz`.

---

## Stage E · Source: Omission of the Superseded Version Filter

- **What we broke:** In `api/app/retrieval/chroma.py`, we removed the query filter `{"superseded": False}`, allowing chunks from `undergraduate-academic-rules-aug-2023.pdf` to compete directly with `academic-rules-handbook-jun-2026.pdf`.
- **Symptom:** When asked "Under current rules, what is the policy on course repeats?", the system returned outdated 2023 rules (which capped repeated course grades) instead of the binding 2026 handbook policy (which retains the most recent grade).
- **Diagnosis (as if not caused on purpose):**
  1. The automated golden evaluation suite flagged a version failure on test question `g09`:
     `Expected 'most recent' in response; found 'grade capped at C'`
  2. Inspecting the retrieved chunk IDs in the response:
     ```json
     "retrieved": [{"chunk_id": "undergraduate-academic-rules-aug-2023.pdf:p14:c0042", "score": 0.89}]
     ```
     The retriever returned a passage with `superseded: true`.
- **Remedy:** Re-implemented the metadata filter `where={"superseded": False}` in `ChromaRetriever.retrieve()`, allowing superseded passages only when the user's question explicitly asks about older or historical rules.
