"""Hosted free-tier provider (Groq, Google AI Studio, OpenRouter)."""

from __future__ import annotations

import json
import logging
from pydantic import ValidationError

from ...config import Settings
from ...schemas import Answer, Passage
from .ollama import SAFE_FALLBACK_ANSWER, _build_prompt

log = logging.getLogger("rahbar.providers.hosted")


class HostedProvider:
    name = "hosted"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _call_hosted(self, messages: list[dict[str, str]]) -> str:
        import httpx

        url = f"{self.settings.hosted_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.settings.llm_model,
            "messages": messages,
            "temperature": self.settings.temperature,
            "response_format": {"type": "json_object"},
        }
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return str(data["choices"][0]["message"]["content"])

    def generate(self, question: str, passages: list[Passage]) -> Answer:
        prompt = _build_prompt(question, passages)
        messages = [{"role": "user", "content": prompt}]

        # Attempt 1
        try:
            raw = self._call_hosted(messages)
            return Answer.model_validate_json(raw)
        except (ValidationError, json.JSONDecodeError, Exception) as exc:
            log.warning("Hosted provider validation failed on attempt 1, retrying once", extra={"error": str(exc)})

        # Retry once
        try:
            retry_messages = [
                {"role": "user", "content": prompt},
                {
                    "role": "user",
                    "content": "Return ONLY valid JSON matching the Answer schema with reasoning, "
                               "answer, citations, answered_from_context, and confidence.",
                },
            ]
            raw_retry = self._call_hosted(retry_messages)
            return Answer.model_validate_json(raw_retry)
        except Exception as retry_exc:
            log.error("Hosted provider validation failed on retry; returning fallback", extra={"error": str(retry_exc)})
            return SAFE_FALLBACK_ANSWER
