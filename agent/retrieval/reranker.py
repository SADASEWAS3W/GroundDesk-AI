"""Pluggable rerankers with strict candidate-bound output validation."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from agent.retrieval.models import RetrievedDocument, validate_top_k

DEFAULT_RERANK_MODEL = "qwen-plus"
DEFAULT_MAX_CANDIDATES = 20
DEFAULT_MAX_DOCUMENT_CHARS = 2000
DEFAULT_MAX_QUERY_CHARS = 1000


class RerankerError(RuntimeError):
    """Base error for provider-backed reranking."""


class RerankerProviderError(RerankerError):
    """Raised when the configured model provider cannot produce a response."""


class RerankerResponseError(RerankerError):
    """Raised when model output violates the candidate-bound contract."""


class NoOpReranker:
    """Preserve candidate order while satisfying the Reranker protocol."""

    async def rerank(
        self,
        query: str,
        documents: Sequence[RetrievedDocument],
        *,
        top_k: int,
    ) -> list[RetrievedDocument]:
        checked_top_k = validate_top_k(top_k)
        return [
            replace(
                document,
                metadata=dict(document.metadata),
                rerank_score=1.0 / rank,
                final_rank=rank,
            )
            for rank, document in enumerate(documents[:checked_top_k], start=1)
        ]


class LLMReranker:
    """Use an injected OpenAI-compatible chat client to score candidates."""

    def __init__(
        self,
        *,
        model_client: Any,
        model: str = DEFAULT_RERANK_MODEL,
        max_candidates: int = DEFAULT_MAX_CANDIDATES,
        max_document_chars: int = DEFAULT_MAX_DOCUMENT_CHARS,
        max_query_chars: int = DEFAULT_MAX_QUERY_CHARS,
    ) -> None:
        if not model.strip():
            raise ValueError("model must not be empty")
        for name, value in (
            ("max_candidates", max_candidates),
            ("max_document_chars", max_document_chars),
            ("max_query_chars", max_query_chars),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")

        self._model_client = model_client
        self._model = model
        self._max_candidates = max_candidates
        self._max_document_chars = max_document_chars
        self._max_query_chars = max_query_chars

    async def rerank(
        self,
        query: str,
        documents: Sequence[RetrievedDocument],
        *,
        top_k: int,
    ) -> list[RetrievedDocument]:
        checked_top_k = validate_top_k(top_k)
        if not documents:
            return []
        if len(documents) > self._max_candidates:
            raise ValueError(
                f"reranker accepts at most {self._max_candidates} candidates"
            )

        candidate_ids = [document.document_id for document in documents]
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("reranker candidates must have unique document_id values")

        payload = {
            "query": query[: self._max_query_chars],
            "candidates": [
                {
                    "document_id": document.document_id,
                    "title": document.title,
                    "content": document.content[: self._max_document_chars],
                }
                for document in documents
            ],
        }
        try:
            response = await self._model_client.chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Rank every supplied document for relevance to the query. "
                            "Return JSON only as {\"rankings\":[{\"document_id\":"
                            "\"candidate-id\",\"score\":0.0}]}. Include each candidate "
                            "exactly once, introduce no IDs, and use finite scores from 0 to 1 "
                            "where larger means more relevant."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=False),
                    },
                ],
                temperature=0,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            raise RerankerProviderError("reranker provider request failed") from exc

        try:
            content = response.choices[0].message.content
            parsed = json.loads(content)
        except Exception as exc:
            raise RerankerResponseError("reranker response is not valid JSON") from exc

        scores = self._validate_rankings(parsed, candidate_ids)
        original_positions = {
            document.document_id: position
            for position, document in enumerate(documents)
        }
        ordered = sorted(
            documents,
            key=lambda document: (
                -scores[document.document_id],
                original_positions[document.document_id],
                document.document_id,
            ),
        )
        return [
            replace(
                document,
                metadata=dict(document.metadata),
                rerank_score=scores[document.document_id],
                final_rank=rank,
            )
            for rank, document in enumerate(ordered[:checked_top_k], start=1)
        ]

    @staticmethod
    def _validate_rankings(
        parsed: Any,
        candidate_ids: Sequence[str],
    ) -> dict[str, float]:
        if not isinstance(parsed, dict) or not isinstance(parsed.get("rankings"), list):
            raise RerankerResponseError("reranker response must contain rankings list")

        allowed_ids = set(candidate_ids)
        scores: dict[str, float] = {}
        for item in parsed["rankings"]:
            if not isinstance(item, dict):
                raise RerankerResponseError("each ranking must be an object")
            document_id = item.get("document_id")
            score = item.get("score")
            if not isinstance(document_id, str) or not document_id:
                raise RerankerResponseError("ranking document_id is required")
            if document_id not in allowed_ids:
                continue
            if document_id in scores:
                continue
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                raise RerankerResponseError("ranking score must be numeric")
            numeric_score = float(score)
            if not math.isfinite(numeric_score) or not 0.0 <= numeric_score <= 1.0:
                raise RerankerResponseError(
                    "ranking score must be finite and between 0 and 1"
                )
            scores[document_id] = numeric_score

        if set(scores) != allowed_ids:
            raise RerankerResponseError(
                "reranker response must cover every candidate exactly once"
            )
        return scores
