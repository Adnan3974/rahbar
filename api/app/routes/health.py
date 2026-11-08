"""Liveness and readiness (section 4.3). They answer different questions."""

from __future__ import annotations

import logging
from fastapi import APIRouter, Request, Response, status

router = APIRouter()
log = logging.getLogger("rahbar.health")


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Is the process alive? Must never touch Chroma, Redis or the LLM."""
    return {"status": "alive"}


@router.get("/readyz")
def readyz(request: Request, response: Response) -> dict[str, object]:
    """Can the service take user traffic now?

    Returns 200 only if:
    1. Embedding model does not conflict with collection metadata.
    2. Chroma is reachable and the collection is non-empty (count() > 0).
    3. Redis semantic cache is reachable.
    Otherwise returns HTTP 503 naming the specific failed dependency.
    """
    settings = request.app.state.settings
    checks: dict[str, str] = {}
    failures: list[str] = []

    # 1. Embedding model guardrail check
    if getattr(request.app.state, "embedding_mismatch", False):
        err = getattr(request.app.state, "embedding_conflict_detail", "EMBED_MODEL mismatch")
        log.error("readyz check failed: " + err)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unready", "error": err, "checks": {"embedding_model": "mismatch"}}

    # If running with stubs (e.g. offline dev/testing), mark ready immediately
    if settings.retriever == "stub":
        checks["retriever"] = "stub"
        checks["collection"] = "ready (stub)"
        return {"status": "ready", "checks": checks}

    # 2. Chroma reachability and non-empty collection check
    try:
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        client = chromadb.HttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        col = client.get_collection(settings.collection)
        chunk_count = col.count()
        if chunk_count == 0:
            failures.append("chroma collection is empty")
            checks["chroma"] = "collection empty (count=0)"
        else:
            checks["chroma"] = f"ok ({chunk_count} chunks)"

        # Re-verify embedding model metadata guardrail
        stored_model = col.metadata.get("embed_model") if col.metadata else None
        if stored_model and stored_model != settings.embed_model:
            msg = f"EMBED_MODEL mismatch: index has {stored_model!r} != config {settings.embed_model!r}"
            failures.append(msg)
            checks["embed_model"] = msg
        else:
            checks["embed_model"] = "matched"
    except Exception as exc:
        failures.append(f"chroma unreachable: {exc}")
        checks["chroma"] = f"unreachable: {exc}"

    # 3. Redis semantic cache reachability check
    try:
        import redis

        r = redis.Redis(host=settings.redis_host, port=settings.redis_port, socket_timeout=1.0)
        r.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        # Note: if Redis is failing, report 503 as required by 4.3
        failures.append(f"redis unreachable: {exc}")
        checks["redis"] = f"unreachable: {exc}"

    if failures:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        log.warning("readiness probe failed", extra={"failures": failures})
        return {"status": "unready", "failures": failures, "checks": checks}

    return {"status": "ready", "checks": checks}
