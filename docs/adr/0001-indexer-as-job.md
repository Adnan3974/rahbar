# ADR 0001: Indexer as a Kubernetes Job

## Status
Accepted · 2026-11-08

## Context
In a grounded RAG architecture running on Kubernetes, the vector store (ChromaDB) must be populated with document embeddings before questions can be accurately answered. A naive architectural choice is to trigger extraction, chunking, and embedding during the API application's startup lifecycle (e.g., inside a FastAPI lifespan event or `@app.on_event("startup")`).

With the API configured to run at 3 replicas for high availability and horizontal scalability, executing the indexing pipeline at startup introduces severe operational hazards:
1. **Concurrent Volume Write Races:** Three API pods starting concurrently attempt to write to the single Chroma volume simultaneously. Without distributed file locks on the underlying persistent volume claim (PVC), simultaneous writes corrupt collection index trees and SQLite metadata stores.
2. **Restart Storms and Amplified Ingestion Costs:** Any pod restart—whether triggered by a rolling update, node drain, OOMKill, or transient probe failure—forces full re-extraction and re-embedding of the entire 40+ page corpus. This wastes memory and compute, degrading cluster responsiveness.
3. **Readiness Falsehoods:** Either the API marks itself ready before indexing completes (serving empty responses and hallucinated declines to users), or readiness is delayed by several minutes while chunking PDFs, causing Kubernetes to time out and enter CrashLoopBackOff. A rolling deployment would kill all working pods while waiting for replacement pods to index.
4. **Tight Coupling and Inability to Re-index on Schedule:** Re-indexing requires a full deployment restart or container rebuild ("the Friday failure" from Lecture 05).

## Decision
We decouple the indexing pipeline entirely from the API service into a standalone Kubernetes `Job` (`rahbar-indexer`) and a recurring `CronJob` (`reindex`).
- The API deployment possesses read-only access to ChromaDB (`RETRIEVER=chroma`). It reads the collection and never writes to it.
- The indexer Job is the sole writer to ChromaDB. It runs as a batch workload with `restartPolicy: OnFailure` and an explicit `backoffLimit`.
- The API's readiness probe (`/readyz`) queries Chroma to ensure the collection exists and contains chunks (`count() > 0`), ensuring traffic is only routed when data is available.
- Re-indexing is triggered on-demand via a single CLI command without touching the API pods:
  ```bash
  kubectl create job --from=cronjob/reindex manual-reindex-1 -n rahbar
  ```

## Options Considered
1. **Indexing in API Lifespan Hook:** Rejected due to multi-replica write collisions, PVC locking failures, and deployment deadlock.
2. **InitContainer on API Pods:** Rejected because initContainers run on *every* replica pod startup, recreating the multi-pod concurrency race and adding substantial startup latency to autoscaling events.
3. **Dedicated Background Microservice with HTTP Endpoint:** Rejected as unnecessarily complex for batch operations that run periodically or on document change.
4. **Kubernetes Job and CronJob (Chosen):** Native Kubernetes batch primitive designed specifically for run-to-completion tasks.

## Consequences
- **Positive:** API pods start in under 2 seconds; scaling from 3 to 8 replicas is instantaneous.
- **Positive:** Zero risk of concurrent write corruption on Chroma's SQLite database.
- **Positive:** Independent resource requests and limits: the indexer can be allocated 1.5Gi memory for PDF extraction and embedding batches without inflating the baseline resource footprint of the API pods.
- **Watch items:** The API must cleanly report 503 on `/readyz` while an initial indexing Job runs, preventing premature traffic routing.
