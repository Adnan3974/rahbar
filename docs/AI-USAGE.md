# AI Usage Attribution

In accordance with course academic integrity policies and Assignment 02 Section 8 guidelines, this document provides honest attribution of all AI tools utilized during the design, development, and debugging of RAHBAR.

| Tool | What it Wrote or Shaped | What We Changed Afterwards, and Why |
|---|---|---|
| Claude / Antigravity Assistant | Scaffolded initial Kubernetes NetworkPolicy ingress/egress rules and Kustomize overlays. | Refined podSelectors to strictly isolate ChromaDB from the UI pod, ensuring UI cannot directly query vector store. Added explicit kube-dns UDP/TCP port 53 egress rules. |
| Claude / Antigravity Assistant | Drafted initial structure-aware chunking regular expressions for numbered heading detection (`1.21 Attendance`). | Adjusted sliding overlap buffer calculations to approximate token counts from word splits and enforced parent section propagation across sub-paragraphs. |
| Claude / Antigravity Assistant | Suggested Redis caching integration patterns and cosine similarity comparison logic. | Implemented strict never-cache constraints for abstentions (`answered_from_context: false`), follow-up prompts, and validation fallback responses to prevent caching invalid answers. |
| GitHub Copilot / Cursor | Generated boilerplate Pydantic schema validation wrappers and Prometheus latency observe handlers. | Added manual schema retry loop and deterministic canned fallback answer to ensure zero 500 status codes on malformed LLM JSON. |
| Claude / Antigravity Assistant | Formatted LaTeX formulas and Markdown tables in documentation and architectural decision records (ADRs). | Reviewed and verified all metric calculations, storage amplification ratios, and line number cross-references against live repository files. |
