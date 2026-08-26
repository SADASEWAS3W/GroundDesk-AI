"""Retrieval service implementations used during staged integration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace

from agent.retrieval.models import (
    RetrievedDocument,
    RetrievalDiagnostics,
    RetrievalResult,
    RetrievalStrategy,
    validate_strategy,
    validate_top_k,
)


def _normalize_query(query: str) -> str:
    return " ".join(query.strip().casefold().split())


class FakeRetrievalService:
    """Deterministic retrieval service for graph, API, and unit-test wiring.

    Exact normalized queries use entries from ``responses``. Unknown queries
    use ``default_documents`` when provided, otherwise they return an explicit
    low-confidence empty result. Returned documents are copies so callers can
    safely enrich them without mutating future fake responses.
    """

    def __init__(
        self,
        responses: Mapping[str, Sequence[RetrievedDocument]] | None = None,
        *,
        default_documents: Sequence[RetrievedDocument] = (),
    ) -> None:
        self._responses = {
            _normalize_query(query): tuple(documents)
            for query, documents in (responses or {}).items()
        }
        self._default_documents = tuple(default_documents)

    async def retrieve(
        self,
        query: str,
        *,
        strategy: RetrievalStrategy = "hybrid_rerank",
        top_k: int = 3,
    ) -> RetrievalResult:
        checked_strategy = validate_strategy(strategy)
        checked_top_k = validate_top_k(top_k)
        normalized_query = _normalize_query(query)

        if not normalized_query:
            return self._empty_result(
                query=query,
                strategy=checked_strategy,
                reason="empty_query",
            )

        source = self._responses.get(normalized_query, self._default_documents)
        documents = [
            replace(
                document,
                metadata=dict(document.metadata),
                final_rank=rank,
            )
            for rank, document in enumerate(source[:checked_top_k], start=1)
        ]

        if not documents:
            return self._empty_result(
                query=query,
                strategy=checked_strategy,
                reason="no_retrieval_results",
            )

        return RetrievalResult(
            query=query,
            documents=documents,
            strategy=checked_strategy,
            diagnostics=RetrievalDiagnostics(
                returned_count=len(documents),
                attributes={"implementation": "fake"},
            ),
        )

    @staticmethod
    def _empty_result(
        *,
        query: str,
        strategy: RetrievalStrategy,
        reason: str,
    ) -> RetrievalResult:
        return RetrievalResult(
            query=query,
            documents=[],
            strategy=strategy,
            low_confidence=True,
            confidence_reasons=[reason],
            diagnostics=RetrievalDiagnostics(
                returned_count=0,
                attributes={"implementation": "fake"},
            ),
        )
