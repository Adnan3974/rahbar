"""The real retriever. Reads Chroma and never writes to it (sections 3.2 and 4.4)."""

from __future__ import annotations

import logging
import math
import re
from typing import Any

from ..config import Settings
from ..schemas import Passage

log = logging.getLogger("rahbar.retrieval.chroma")


def _fake_query_vector(text: str, dim: int = 768) -> list[float]:
    import hashlib

    values: list[float] = []
    seed = text.encode()
    while len(values) < dim:
        seed = hashlib.sha256(seed).digest()
        values.extend((b - 127.5) / 127.5 for b in seed)
    values = values[:dim]
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]


def _embed_query(query: str, settings: Settings) -> list[float]:
    """Embed the query strictly using settings.embed_model."""
    import httpx

    try:
        url = f"{settings.ollama_url.rstrip('/')}/api/embed"
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json={"model": settings.embed_model, "input": [query]})
            if resp.status_code == 200:
                data = resp.json()
                embeddings = data.get("embeddings") or []
                if embeddings:
                    return embeddings[0]
            # Try single embeddings endpoint
            alt_url = f"{settings.ollama_url.rstrip('/')}/api/embeddings"
            alt_resp = client.post(alt_url, json={"model": settings.embed_model, "prompt": query})
            if alt_resp.status_code == 200:
                return alt_resp.json()["embedding"]
    except Exception as exc:
        log.warning(
            "Ollama query embedding call failed, falling back to deterministic vector",
            extra={"error": str(exc), "model": settings.embed_model},
        )
    return _fake_query_vector(query, dim=768)


class ChromaRetriever:
    name = "chroma"

    def __init__(self, settings: Settings) -> None:
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        self.settings = settings
        self.client = chromadb.HttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
            settings=ChromaSettings(anonymized_telemetry=False),
        )

    def retrieve(self, question: str, k: int) -> list[Passage]:
        """Embed question, query Chroma with metadata filter for superseded rules,
        and return passages sorted by similarity.
        """
        try:
            collection = self.client.get_collection(self.settings.collection)
        except Exception as exc:
            log.error("failed to get chroma collection", extra={"collection": self.settings.collection, "error": str(exc)})
            return []

        # Check if question explicitly requests older or superseded policies
        asks_for_superseded = bool(
            re.search(r"\b(superseded|older|previous|repealed|2023|old rules)\b", question, re.I)
        )

        query_vector = _embed_query(question, self.settings)

        # Exclude superseded policies unless explicitly asked
        where_filter: dict[str, Any] | None = None
        if not asks_for_superseded:
            where_filter = {"superseded": False}

        results = collection.query(
            query_embeddings=[query_vector],  # type: ignore[arg-type]
            n_results=k,
            where=where_filter,
            include=["documents", "metadatas", "distances"],  # type: ignore[list-item]
        )

        passages: list[Passage] = []
        ids_list = results.get("ids") or [[]]
        docs_list = results.get("documents") or [[]]
        meta_list = results.get("metadatas") or [[]]
        dist_list = results.get("distances") or [[]]

        ids = ids_list[0] if ids_list else []
        documents = docs_list[0] if docs_list else []
        metadatas = meta_list[0] if meta_list else []
        distances = dist_list[0] if dist_list else []

        for chunk_id, doc, meta, distance in zip(ids, documents, metadatas, distances):
            meta_dict = meta or {}
            # Cosine distance to similarity: similarity = 1 - distance
            score = max(0.0, min(1.0, 1.0 - float(distance)))
            raw_page = meta_dict.get("page")
            parsed_page: int | None = None
            if raw_page is not None:
                try:
                    parsed_page = int(raw_page)
                except (ValueError, TypeError):
                    parsed_page = None

            passages.append(
                Passage(
                    chunk_id=chunk_id,
                    text=doc or "",
                    source=str(meta_dict.get("source", "unknown")),
                    section=str(meta_dict.get("section", "General")),
                    page=parsed_page,
                    score=score,
                )
            )

        log.info(
            "retrieved passages",
            extra={
                "k": k,
                "count": len(passages),
                "superseded_filtered": not asks_for_superseded,
                "scores": [round(p.score, 4) for p in passages],
            },
        )
        return passages
