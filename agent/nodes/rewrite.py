"""Single-query rewrite implementations with a deterministic fallback."""

from __future__ import annotations

import asyncio
import os
from typing import Protocol


class RewriteProviderError(RuntimeError):
    pass


class QueryRewriter(Protocol):
    async def rewrite(self, query: str) -> str: ...


class DeterministicQueryRewriter:
    async def rewrite(self, query: str) -> str:
        return " ".join(query.strip().split())


class LLMQueryRewriter:
    """Rewrite one customer message into one concise retrieval query."""

    def __init__(
        self,
        model_client,
        *,
        model: str | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._client = model_client
        self._model = model or os.environ.get("QWEN_CHAT_MODEL", "qwen-plus")
        self._timeout_seconds = timeout_seconds

    async def rewrite(self, query: str) -> str:
        normalized = " ".join(query.strip().split())
        if not normalized:
            return ""
        try:
            response = await asyncio.wait_for(
                self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Rewrite the customer message as one concise knowledge-base "
                                "search query. Preserve product names, error codes, language, "
                                "and intent. Return only the rewritten query."
                            ),
                        },
                        {"role": "user", "content": normalized},
                    ],
                    temperature=0,
                ),
                timeout=self._timeout_seconds,
            )
            rewritten = (response.choices[0].message.content or "").strip()
        except Exception as exc:
            raise RewriteProviderError("query rewrite provider failed") from exc
        if not rewritten:
            raise RewriteProviderError("query rewrite provider returned empty output")
        return " ".join(rewritten.split())
