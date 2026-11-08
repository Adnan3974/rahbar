"""Redis-backed semantic cache layer for RAHBAR (section 3.3)."""

from __future__ import annotations

import json
import logging
import math
import re
from typing import Any

from ..config import Settings
from ..schemas import AskResponse

log = logging.getLogger("rahbar.cache")


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a)) or 1.0
    norm_b = math.sqrt(sum(b * b for b in vec_b)) or 1.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


def is_followup_question(question: str) -> bool:
    """Detect if a question is a contextual follow-up that relies on earlier turns."""
    pattern = r"^(and\b|what about|how about|also\b|why\b|does it\b|can they\b|in that case|then\b)"
    return bool(re.search(pattern, question.strip(), re.I))


def should_never_cache(question: str, response: AskResponse) -> bool:
    """Never cache follow-up questions, abstentions, out-of-scope answers, or fallbacks."""
    if is_followup_question(question):
        return True
    if not response.answered_from_context:
        return True
    if response.confidence == "low" and not response.citations:
        return True
    return False


class SemanticCache:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._redis: Any = None

    def _get_client(self) -> Any:
        if self._redis is None:
            try:
                import redis

                self._redis = redis.Redis(
                    host=self.settings.redis_host,
                    port=self.settings.redis_port,
                    socket_timeout=1.0,
                    decode_responses=True,
                )
            except Exception as exc:
                log.warning("could not connect to Redis semantic cache", extra={"error": str(exc)})
                return None
        return self._redis

    def get(self, question: str, query_vector: list[float]) -> AskResponse | None:
        """Search the cache for entries meeting or exceeding the similarity threshold."""
        if is_followup_question(question):
            log.info("skipping cache lookup for follow-up question")
            return None

        r = self._get_client()
        if r is None:
            return None

        try:
            keys = r.keys("rahbar:cache:*")
            if not keys:
                return None

            best_score = 0.0
            best_entry: dict[str, Any] | None = None

            for key in keys:
                raw = r.get(key)
                if not raw:
                    continue
                entry = json.loads(raw)
                cached_vec = entry.get("vector")
                if cached_vec:
                    sim = _cosine_similarity(query_vector, cached_vec)
                    if sim > best_score:
                        best_score = sim
                        best_entry = entry

            # Check threshold
            if best_score >= self.settings.cache_threshold and best_entry:
                resp_data = best_entry["response"]
                log.info(
                    "semantic cache hit",
                    extra={"score": round(best_score, 4), "threshold": self.settings.cache_threshold},
                )
                return AskResponse.model_validate(resp_data)
        except Exception as exc:
            log.warning("semantic cache lookup failed", extra={"error": str(exc)})

        return None

    def set(self, question: str, query_vector: list[float], response: AskResponse) -> None:
        """Store a successful turn in the cache if it meets caching rules."""
        if should_never_cache(question, response):
            log.info("turn marked never_cache; skipping cache write")
            return

        r = self._get_client()
        if r is None:
            return

        try:
            import hashlib

            h = hashlib.sha256(question.encode()).hexdigest()[:16]
            key = f"rahbar:cache:{h}"
            payload = {
                "question": question,
                "vector": query_vector,
                "response": response.model_dump(),
            }
            # Cache TTL 7 days (604800s)
            r.setex(key, 604800, json.dumps(payload))
            log.info("cached question response", extra={"key": key})
        except Exception as exc:
            log.warning("could not write to semantic cache", extra={"error": str(exc)})

    def invalidate(self) -> None:
        """Flush the cache (invoked on re-indexing)."""
        r = self._get_client()
        if r:
            try:
                r.flushdb()
                log.info("semantic cache invalidated successfully")
            except Exception as exc:
                log.warning("failed to flush semantic cache", extra={"error": str(exc)})
