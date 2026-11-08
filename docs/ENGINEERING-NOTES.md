# Engineering Notes

This document provides rigorous answers to the seven mandatory architectural questions from Section 7 of Assignment 02, referencing exact files, manifests, and line numbers in the RAHBAR repository.

---

## 1. Indexing in API Startup: What Breaks with 3 Replicas and One Chroma Volume?

### The Failure Mode
If the indexing pipeline (PDF extraction, text cleaning, chunking, and ChromaDB vector persistence) runs inside the API startup lifecycle (e.g., inside FastAPI's `lifespan` in [`api/app/main.py`](file:///home/adnan/Downloads/scd02%20solution/api/app/main.py#L28-L45)):
1. **Multi-Writer SQLite Lock Contention:** ChromaDB relies on an underlying SQLite database and parquet storage on a single PersistentVolumeClaim (`chroma-data`). When the API scales to 3 replicas ([`k8s/base/api-deployment.yaml#L11`](file:///home/adnan/Downloads/scd02%20solution/k8s/base/api-deployment.yaml#L11)), three distinct pods concurrently execute `collection.add()` or `client.create_collection()`. SQLite throws `sqlite3.OperationalError: database is locked`, corrupting the HNSW index graphs.
2. **Cascading Re-indexing on Restarts:** Any pod restart (such as an eviction, rolling update, or OOMKill) forces that pod to re-extract and re-embed all 224 pages of the corpus, consuming significant compute and saturating the Ollama endpoint.
3. **Readiness Probe Deadlock:** Either pods report ready before indexing is complete (serving empty retrievals and false abstentions), or their readiness probe times out while waiting for 5 minutes of PDF embedding, causing Kubernetes to kill the pod before it ever takes traffic.

### The Preventing Object
The architecture strictly enforces the **One Writer, Many Readers** pattern:
- The writer is decoupled into a dedicated Kubernetes batch `Job` ([`k8s/base/indexer-job.yaml#L2`](file:///home/adnan/Downloads/scd02%20solution/k8s/base/indexer-job.yaml#L2)) and `CronJob` ([`k8s/base/reindex-cronjob.yaml#L2`](file:///home/adnan/Downloads/scd02%20solution/k8s/base/reindex-cronjob.yaml#L2)).
- The API Deployment only reads from ChromaDB ([`api/app/retrieval/chroma.py#L65`](file:///home/adnan/Downloads/scd02%20solution/api/app/retrieval/chroma.py#L65)).
- The manifest object preventing API startup indexing is [`k8s/base/indexer-job.yaml`](file:///home/adnan/Downloads/scd02%20solution/k8s/base/indexer-job.yaml#L1-L45), with `restartPolicy: OnFailure` and `backoffLimit: 3`.

---

## 2. Readiness and Liveness Swapped, Chroma Slow for 90 Seconds: What Happens?

### The Swap Disaster
In Kubernetes:
- `livenessProbe` answers: *Is the container process alive?* If it fails, kubelet restarts/kills the pod.
- `readinessProbe` answers: *Can the container accept incoming HTTP traffic?* If it fails, the pod is temporarily removed from the Service Endpoints without restarting.

In [`k8s/base/api-deployment.yaml#L70-L85`](file:///home/adnan/Downloads/scd02%20solution/k8s/base/api-deployment.yaml#L70-L85), `livenessProbe` targets `/healthz` (which touches zero dependencies; see [`api/app/routes/health.py#L13-L16`](file:///home/adnan/Downloads/scd02%20solution/api/app/routes/health.py#L13-L16)), while `readinessProbe` targets `/readyz` (which checks Chroma reachability and collection count; see [`api/app/routes/health.py#L19-L65`](file:///home/adnan/Downloads/scd02%20solution/api/app/routes/health.py#L19-L65)).

If an engineer accidentally swaps them:
1. `livenessProbe` checks Chroma, while `readinessProbe` checks `/healthz`.
2. When Chroma experiences transient load or a 90-second slow period:
   - With `periodSeconds: 20` and `failureThreshold: 3` ([`k8s/base/api-deployment.yaml#L74-L77`](file:///home/adnan/Downloads/scd02%20solution/k8s/base/api-deployment.yaml#L74-L77)), three successive liveness probe timeouts occur after 60 seconds.
   - Kubelet forcefully terminates all 3 API replicas simultaneously and restarts their containers.
   - Upon restarting, all 3 new pods attempt to connect to the still-recovering Chroma instance. Their liveness probes fail again.
   - **The Cluster-Wide Restart Storm:** All 3 API replicas enter `CrashLoopBackOff`. What was merely a slow dependency has now escalated into complete cluster unavailability.
3. With our correct design, `/readyz` fails during the slow period: kubelet simply removes the pods from the Service endpoints without killing them. As soon as Chroma responds at second 91, the endpoints are reinstated with zero container restarts.

---

## 3. What Does a CPU-Based HPA Actually Measure on a Generation Service, and What Should Scale It?

### The 8% CPU Paradox
Our Horizontal Pod Autoscaler ([`k8s/base/hpa.yaml#L1-L24`](file:///home/adnan/Downloads/scd02%20solution/k8s/base/hpa.yaml#L1-L24)) tracks average CPU utilization against requested CPU (`70%`).

However, on a RAG generation service:
- When a user submits a question, the API embeds the query in ~20ms and retrieves chunks in ~15ms.
- The API then makes an outbound HTTP call to the LLM provider ([`api/app/providers/llm/ollama.py#L74-L86`](file:///home/adnan/Downloads/scd02%20solution/api/app/providers/llm/ollama.py#L74-L86)) and blocks asynchronously awaiting model tokens (taking 2.5–4.5 seconds).
- From the API pod's CPU perspective, the container is **I/O bound**, sitting idle in an event loop wait. Even during heavy traffic spikes, CPU utilization rarely exceeds 15–25% (as demonstrated in [`docs/evidence/kubectl-top.txt`](file:///home/adnan/Downloads/scd02%20solution/docs/evidence/kubectl-top.txt)).
- The CPU-based HPA therefore measures Python's JSON serialization and HTTP protocol parsing overhead—**not** the actual service bottleneck or system saturation!

### The True Scaling Signal and What is Needed to Build It
The true scaling signal for a RAG service is **In-Flight Concurrent Request Count** or **Waiting Request Queue Depth**.
To use this signal:
1. Deploy the Prometheus Custom Metrics Adapter (`k8s-prometheus-adapter`).
2. Leverage the `/metrics` endpoint ([`api/app/routes/metrics.py`](file:///home/adnan/Downloads/scd02%20solution/api/app/routes/metrics.py)), which exposes `rahbar_requests_in_flight`.
3. Configure the HPA to scale on custom metric `http_requests_in_flight_per_pod` with a target threshold (e.g., target 5 concurrent requests per API pod).

---

## 4. Indexer Peak Memory, Limit, Margin, and Exit Code When Set Wrong

### Real Measurements from `kubectl top pods`
As committed in [`docs/evidence/kubectl-top.txt`](file:///home/adnan/Downloads/scd02%20solution/docs/evidence/kubectl-top.txt):
- Peak indexer memory recorded during extraction and batch embedding of the 62-page Student Handbook: **412 MiB**.
- In [`k8s/base/indexer-job.yaml#L33-L38`](file:///home/adnan/Downloads/scd02%20solution/k8s/base/indexer-job.yaml#L33-L38):
  - `requests.memory`: `512Mi`
  - `limits.memory`: `1536Mi`

### Margin Analysis
$$\text{Safety Margin} = \frac{\text{Memory Limit} - \text{Peak Usage}}{\text{Peak Usage}} = \frac{1536\text{ Mi} - 412\text{ Mi}}{412\text{ Mi}} \approx 272\%$$
This >2.7x margin comfortably accommodates larger annual reports and spikes during image rendering for OCR without risk.

### Exit Code When Set Wrong
If memory limit is set too low (e.g. 256Mi):
The Linux kernel OOM Killer immediately terminates the indexer process with signal 9 (SIGKILL). Kubernetes reports container failure with:
$$\text{Exit Code } 137 \quad (128 + 9 = 137)$$
The Job transitions into `OOMKilled` and subsequently enters `CrashLoopBackOff`.

---

## 5. recall@5 by Question Type: Where Is It Worst, and Why?

### Empirical Results from `eval/results.json`
From our committed evaluation results ([`eval/results.json`](file:///home/adnan/Downloads/scd02%20solution/eval/results.json)):
- **Ordinary questions:** `recall@5 = 94.25%`
- **Version-sensitive questions:** `recall@5 = 91.50%`
- **Exact-term questions:** `recall@5 = 88.00%` (Visibly Worst)

### Why Embeddings Struggle on Exact Terms
Dense embedding models like `nomic-embed-text` project text into continuous semantic manifolds. They are trained to maximize cosine similarity between conceptually related phrases (e.g., "minimum attendance" maps near "class presence requirements").

However, exact numerical thresholds ("2.00" vs "1.70"), course codes ("CS4032" vs "CS4033"), and clause numbers ("Clause 1.21" vs "Clause 1.22") have near-identical vector representations. The vector space blurs small digit variations, causing semantic search to return the wrong subclause.

### Addressing Technique from RAG Lecture
The technique taught in the RAG lecture is **Hybrid Search**: combining dense semantic vector retrieval with sparse keyword indexing (BM25 or SPLADE) and Reciprocal Rank Fusion (RRF), paired with strict metadata filtering on structured clause fields.

---

## 6. EMBED_MODEL Changed in ConfigMap and API Restarted: What Happens?

### System Behavior Under Guardrail
If someone changes `EMBED_MODEL` in [`k8s/base/configmap.yaml`](file:///home/adnan/Downloads/scd02%20solution/k8s/base/configmap.yaml#L6) from `nomic-embed-text` to `all-MiniLM-L6-v2` and restarts the API deployment without running the indexer Job:
1. During pod startup, the guardrail in [`api/app/main.py#L38-L54`](file:///home/adnan/Downloads/scd02%20solution/api/app/main.py#L38-L54) inspects the Chroma collection metadata.
2. It detects: `stored_model ('nomic-embed-text') != settings.embed_model ('all-MiniLM-L6-v2')`.
3. It sets `app.state.embedding_mismatch = True` and logs:
   `guardrail triggered: embedding model mismatch: collection was indexed with 'nomic-embed-text' but API EMBED_MODEL is 'all-MiniLM-L6-v2'`
4. The `/readyz` probe ([`api/app/routes/health.py#L29-L34`](file:///home/adnan/Downloads/scd02%20solution/api/app/routes/health.py#L29-L34)) returns `HTTP 503 Service Unavailable`.
5. The API pod remains at `0/1 READY` in `kubectl get pods` and is excluded from the Service endpoints.

### What Would Have Happened Without the Guardrail?
Without this guardrail, the system suffers a **Silent Semantic Catastrophe**:
The API embeds user queries into a 384-dimensional vector space, while Chroma attempts to query against 768-dimensional document vectors (or Chroma silently pads/distorts dimensions). Retrieval distances become random mathematical noise. The model receives completely unrelated context, producing hallucinated answers or false declines while reporting `HTTP 200 OK` and showing healthy green probes.

---

## 7. The Failure That Cost Us More Than an Hour

### Symptoms
When executing `make install`, the command terminated with:
```bash
/bin/bash: line 1: /home/adnan/Downloads/scd02: Is a directory
make: *** [Makefile:23: install] Error 126
```
Attempts to run `make test`, `make lint`, and `check_submission.py` were completely blocked.

### What We Wrongly Believed First
We initially suspected that Python 3.12 had created a corrupted virtual environment or that `/home/adnan/Downloads/scd02` had file permission issues resulting from root ownership. We spent time inspecting file permissions with `ls -la` and attempting to re-run virtual environment creations manually.

### The Truth Revealed
The diagnostic truth was revealed when running `bash -x -c 'make install'`:
In [`Makefile#L9`](file:///home/adnan/Downloads/scd02%20solution/Makefile#L9):
```makefile
BIN := $(abspath $(VENV))/bin
```
The workspace folder was named `/home/adnan/Downloads/scd02 solution` (containing a literal space!).
In Makefile line 23:
```makefile
$(BIN)/pip install -q --upgrade pip
```
Because `$(BIN)` was unquoted, bash expanded it to:
`/home/adnan/Downloads/scd02 solution/.venv/bin/pip`
Bash interpreted `/home/adnan/Downloads/scd02` as the executable command name, and `solution/.venv/bin/pip` as the argument! Since `/home/adnan/Downloads/scd02` is a directory, the kernel returned `Error 126: Is a directory`.

### The Remedy
We quoted all executable variables across the [`Makefile`](file:///home/adnan/Downloads/scd02%20solution/Makefile) (`"$(BIN)/pip"`, `"$(BIN)/pytest"`, `"$(BIN)/ruff"`, `"$(BIN)/mypy"`), fully resolving the issue and enabling clean execution across directory paths containing spaces.
