# ADR 0003: Redis as the Semantic Cache Store

## Status
Accepted · 2026-11-08

## Context
Natural language queries submitted to university question-answering systems exhibit significant semantic overlap (e.g., "What attendance is needed for exams?" vs "Minimum attendance percentage required to sit final exam"). Running full vector retrieval, reranking, augmented prompt compilation, and large language model inference for duplicate or near-duplicate queries introduces latency (2–5 seconds per request) and consumes expensive compute resources.

A semantic caching layer intercepts questions, computes their query embedding, and checks if a previously validated answer satisfies a cosine similarity threshold.

## Decision
We implement the semantic cache using **Redis** backed by a PersistentVolumeClaim (`Deployment + PVC redis`):
1. **Cosine Similarity Evaluation:** When a query arrives, its embedding vector is compared against cached query vectors. If cosine similarity meets or exceeds `CACHE_THRESHOLD` (0.90, calibrated against false hits), the cached `AskResponse` is returned immediately with `"cached": true`.
2. **Never-Cache Constraints:** To avoid polluting the cache with errors or incorrect answers:
   - Abstentions (`answered_from_context: false`) are NEVER cached.
   - Questions that failed schema validation or fell back to canned answers are NEVER cached.
   - Out-of-scope or conversational follow-up turns are NEVER cached.
3. **Cache Invalidation on Re-index:** When an indexing Job runs and updates the ChromaDB collection, it flushes or invalidates the Redis cache. Serving outdated answers from an expired corpus version is an unacceptable silent failure mode.

## Options Considered
1. **Second ChromaDB Collection:**
   - *Pros:* Native vector index capabilities.
   - *Cons:* ChromaDB is designed for persistent static document indices rather than high-frequency dynamic key-value cache operations with rapid expiration, TTLs, and atomic flush semantics.
2. **In-Memory Python Dictionary:**
   - *Pros:* Simple to code.
   - *Cons:* State is confined to a single process. Across 3 API replicas, each pod maintains an isolated, fragmented cache. Cache is completely lost on pod restart.
3. **Redis Key-Value / Vector Store (Chosen):**
   - *Pros:* Shared across all API replicas, sub-millisecond read latency, native persistence via PVC, simple TTL support, and trivial atomic flush (`FLUSHDB`) on indexer completion.

## Consequences
- **Positive:** Reduces average query latency for repeated questions from ~3500ms to <20ms.
- **Positive:** Centralized cache across all 3 API replicas with PVC survival across pod restarts.
- **Watch items:** The cache threshold must be strictly maintained >= 0.88 to avoid false positive matches on distinct clauses with similar syntactic structure (e.g., warning vs probation thresholds).
