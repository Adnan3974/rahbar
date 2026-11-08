"""Stage 5: Store. The only code in the whole system that writes to Chroma."""

from __future__ import annotations

import logging
import os
from typing import Any

from .config import IndexerSettings
from .models import Chunk

log = logging.getLogger("rahbar.indexer.store")


def get_client(settings: IndexerSettings) -> Any:
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    return chromadb.HttpClient(
        host=settings.chroma_host,
        port=settings.chroma_port,
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def _invalidate_semantic_cache() -> None:
    """Invalidate semantic cache in Redis when index is updated."""
    redis_host = os.environ.get("REDIS_HOST", "redis")
    redis_port = int(os.environ.get("REDIS_PORT", "6379"))
    try:
        import redis

        r = redis.Redis(host=redis_host, port=redis_port, socket_timeout=2.0)
        r.flushdb()
        log.info("invalidated semantic cache after re-indexing")
    except Exception as exc:
        log.warning("could not flush Redis cache (service might be absent)", extra={"error": str(exc)})


def store(chunks: list[Chunk], vectors: list[list[float]], settings: IndexerSettings) -> int:
    """Write every chunk with its vector and metadata, and record the embedding model
    and vector dimension in the collection metadata (section 4.4). Return the count.
    """
    if not chunks:
        return 0

    client = get_client(settings)
    dimension = len(vectors[0]) if vectors else 768

    # Recreate or get collection with pinned model metadata
    try:
        client.delete_collection(settings.collection)
    except Exception:
        pass

    collection = client.create_collection(
        name=settings.collection,
        metadata={
            "embed_model": settings.embed_model,
            "dimension": dimension,
            "hnsw:space": "cosine",
        },
    )

    # Batch inserts into Chroma
    batch_size = 50
    for i in range(0, len(chunks), batch_size):
        c_batch = chunks[i : i + batch_size]
        v_batch = vectors[i : i + batch_size]
        collection.add(
            ids=[c.id for c in c_batch],
            documents=[c.text for c in c_batch],
            embeddings=v_batch,
            metadatas=[c.metadata() for c in c_batch],
        )

    # Expire/invalidate semantic cache to avoid serving stale answers
    _invalidate_semantic_cache()

    log.info(
        "stored chunks",
        extra={
            "chunks": len(chunks),
            "collection": settings.collection,
            "embed_model": settings.embed_model,
            "dimension": dimension,
        },
    )
    return len(chunks)
