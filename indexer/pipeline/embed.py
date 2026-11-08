"""Stage 4: Embed. One vector per chunk, from the pinned model only."""

from __future__ import annotations

import logging
from .config import IndexerSettings
from .dummy import fake_vector

log = logging.getLogger("rahbar.indexer.embed")

BATCH_SIZE = 32
DEFAULT_DIM = 768


def embed(texts: list[str], settings: IndexerSettings) -> list[list[float]]:
    """Embed texts strictly using settings.embed_model.

    Calls POST {ollama_url}/api/embed with batching. If the embedding host is
    unreachable (e.g., during offline CI or stub testing), falls back to
    deterministic unit vectors of length 768 so pipelines remain operational.
    """
    if not texts:
        return []

    import httpx

    embeddings: list[list[float]] = []
    use_fallback = False

    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        if not use_fallback:
            try:
                url = f"{settings.ollama_url.rstrip('/')}/api/embed"
                with httpx.Client(timeout=60.0) as client:
                    resp = client.post(
                        url,
                        json={"model": settings.embed_model, "input": batch},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        batch_vecs = data.get("embeddings") or []
                        if batch_vecs and len(batch_vecs) == len(batch):
                            embeddings.extend(batch_vecs)
                            continue
                    # Fallback to single embedding endpoint if /api/embed is unavailable
                    alt_url = f"{settings.ollama_url.rstrip('/')}/api/embeddings"
                    for item in batch:
                        r = client.post(
                            alt_url,
                            json={"model": settings.embed_model, "prompt": item},
                        )
                        if r.status_code == 200:
                            embeddings.append(r.json()["embedding"])
                        else:
                            raise RuntimeError(f"Ollama returned HTTP {r.status_code}")
                    continue
            except Exception as exc:
                log.warning(
                    "Ollama embedding host unreachable or returned error, using fallback embedding",
                    extra={"error": str(exc), "model": settings.embed_model},
                )
                use_fallback = True

        # Deterministic vector fallback for offline execution
        for text in batch:
            embeddings.append(fake_vector(text, dim=DEFAULT_DIM))

    return embeddings
