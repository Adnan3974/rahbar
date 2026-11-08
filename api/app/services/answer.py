"""Turns a question into an AskResponse. This is where the query pipeline lives (section 3.2)."""

from __future__ import annotations

import logging

from ..config import Settings
from ..logjson import request_id_var
from ..providers.llm.base import LLMProvider
from ..retrieval.base import Retriever
from ..retrieval.chroma import _embed_query
from ..schemas import AskResponse, Citation, RetrievedRef
from .cache import SemanticCache

log = logging.getLogger("rahbar.answer")


def _filter_invalid_citations(citations: list[Citation], retrieved_refs: list[RetrievedRef]) -> list[Citation]:
    """Ensure every citation in the answer corresponds to a chunk actually retrieved."""
    valid_pairs = {(r.source.strip().lower(), r.section.strip().lower()) for r in retrieved_refs}
    valid_sources = {r.source.strip().lower() for r in retrieved_refs}

    validated: list[Citation] = []
    for c in citations:
        c_src = c.source.strip().lower()
        c_sec = c.section.strip().lower()
        # Exact match or source match with non-empty section
        if (c_src, c_sec) in valid_pairs or c_src in valid_sources:
            validated.append(c)
        else:
            log.warning("filtered fabricated citation not present in retrieved context",
                        extra={"citation": c.model_dump()})
    return validated


def answer_question(
    question: str, retriever: Retriever, provider: LLMProvider, settings: Settings
) -> AskResponse:
    rid = request_id_var.get()
    cache = SemanticCache(settings)

    # 1. Validation & query embedding
    query_vector = _embed_query(question, settings)

    # 2. Semantic cache check (skipped for follow-up questions)
    cached_response = cache.get(question, query_vector)
    if cached_response is not None:
        return cached_response

    # 3. Retrieve passages from Chroma or Stub
    passages = retriever.retrieve(question, k=settings.top_k)

    retrieved_refs = [
        RetrievedRef(
            chunk_id=p.chunk_id,
            source=p.source,
            section=p.section,
            page=p.page,
            score=round(p.score, 4),
        )
        for p in passages
    ]

    # 4. Relevance floor & honest abstention check (Section 3.4)
    # If no passages retrieved or highest similarity score < relevance_floor, decline honestly
    max_score = max((p.score for p in passages), default=0.0)
    if not passages or max_score < settings.relevance_floor:
        log.info(
            "relevance floor triggered abstention",
            extra={
                "max_score": round(max_score, 4),
                "relevance_floor": settings.relevance_floor,
                "question": question,
            },
        )
        decline_response = AskResponse(
            request_id=rid,
            answer="The document corpus does not contain sufficient authoritative information to answer this question.",
            citations=[],
            answered_from_context=False,
            confidence="low",
            retrieved=retrieved_refs,
            provider=provider.name,
        )
        return decline_response

    # 5. Generate answer via LLM provider
    answer = provider.generate(question, passages)

    # 6. Enforce citation validity: every citation must match a retrieved passage
    valid_citations = _filter_invalid_citations(answer.citations, retrieved_refs)

    response = AskResponse(
        request_id=rid,
        answer=answer.answer,
        citations=valid_citations,
        answered_from_context=answer.answered_from_context,
        confidence=answer.confidence,
        retrieved=retrieved_refs,
        provider=provider.name,
    )

    # 7. Store safe responses in semantic cache
    cache.set(question, query_vector, response)

    # 8. Observability log
    log.info(
        "answered",
        extra={
            "retriever": retriever.name,
            "provider": provider.name,
            "top_k": settings.top_k,
            "chunk_ids": [p.chunk_id for p in passages],
            "scores": [round(p.score, 4) for p in passages],
            "answered_from_context": response.answered_from_context,
            "citations_count": len(valid_citations),
        },
    )

    return response
