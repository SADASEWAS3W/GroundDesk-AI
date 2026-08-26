"""Retrieval service implementations used during staged integration."""

from __future__ import annotations

import asyncio
import time
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
from agent.retrieval.protocols import BM25Retriever, FusionStrategy, VectorRetriever


def _normalize_query(query: str) -> str:
    return " ".join(query.strip().casefold().split())


class RetrievalCapabilityError(RuntimeError):
    """Raised when a requested pipeline stage has not been configured."""


class HybridRetrievalService:
    """Compose vector, BM25, and RRF behind the stable service boundary."""

    def __init__(
        self,
        *,
        vector_retriever: VectorRetriever,
        bm25_retriever: BM25Retriever,
        fusion_strategy: FusionStrategy,
        candidate_top_k: int = 10,
    ) -> None:
        self._vector_retriever = vector_retriever
        self._bm25_retriever = bm25_retriever
        self._fusion_strategy = fusion_strategy
        self._candidate_top_k = validate_top_k(candidate_top_k)

    async def retrieve(
        self,
        query: str,
        *,
        strategy: RetrievalStrategy = "hybrid",
        top_k: int = 3,
    ) -> RetrievalResult:
        checked_strategy = validate_strategy(strategy)
        checked_top_k = validate_top_k(top_k)
        normalized_query = " ".join(query.strip().split())
        if not normalized_query:
            return self._empty_result(query=query, strategy=checked_strategy, reason="empty_query")
        if checked_strategy == "hybrid_rerank":
            raise RetrievalCapabilityError(
                "hybrid_rerank requires a reranker; it is introduced in stage five"
            )

        started = time.perf_counter()
        if checked_strategy == "vector_only":
            vector_started = time.perf_counter()
            vector_documents = await self._vector_retriever.search(
                normalized_query,
                top_k=checked_top_k,
            )
            vector_latency = (time.perf_counter() - vector_started) * 1000
            documents = [
                replace(document, metadata=dict(document.metadata), final_rank=rank)
                for rank, document in enumerate(
                    vector_documents[:checked_top_k],
                    start=1,
                )
            ]
            diagnostics = RetrievalDiagnostics(
                vector_candidate_count=len(vector_documents),
                returned_count=len(documents),
                vector_latency_ms=vector_latency,
                total_latency_ms=(time.perf_counter() - started) * 1000,
            )
        else:
            candidate_top_k = max(self._candidate_top_k, checked_top_k)
            vector_task = asyncio.create_task(
                self._timed_search(
                    self._vector_retriever,
                    normalized_query,
                    top_k=candidate_top_k,
                )
            )
            bm25_task = asyncio.create_task(
                self._timed_search(
                    self._bm25_retriever,
                    normalized_query,
                    top_k=candidate_top_k,
                )
            )
            try:
                (
                    (vector_documents, vector_latency),
                    (bm25_documents, bm25_latency),
                ) = await asyncio.gather(vector_task, bm25_task)
            except Exception:
                vector_task.cancel()
                bm25_task.cancel()
                await asyncio.gather(vector_task, bm25_task, return_exceptions=True)
                raise
            fusion_started = time.perf_counter()
            fused_documents = self._fusion_strategy.fuse(
                vector_documents,
                bm25_documents,
                top_k=min(
                    100,
                    len({
                        document.document_id
                        for document in (*vector_documents, *bm25_documents)
                    }) or 1,
                ),
            )
            documents = fused_documents[:checked_top_k]
            finished = time.perf_counter()
            diagnostics = RetrievalDiagnostics(
                vector_candidate_count=len(vector_documents),
                bm25_candidate_count=len(bm25_documents),
                fused_candidate_count=len(fused_documents),
                returned_count=len(documents),
                vector_latency_ms=vector_latency,
                bm25_latency_ms=bm25_latency,
                fusion_latency_ms=(finished - fusion_started) * 1000,
                total_latency_ms=(finished - started) * 1000,
            )

        if not documents:
            return RetrievalResult(
                query=query,
                documents=[],
                strategy=checked_strategy,
                low_confidence=True,
                confidence_reasons=["no_retrieval_results"],
                diagnostics=diagnostics,
            )
        return RetrievalResult(
            query=query,
            documents=documents,
            strategy=checked_strategy,
            diagnostics=diagnostics,
        )

    @staticmethod
    async def _timed_search(
        retriever: VectorRetriever | BM25Retriever,
        query: str,
        *,
        top_k: int,
    ) -> tuple[list[RetrievedDocument], float]:
        started = time.perf_counter()
        documents = await retriever.search(query, top_k=top_k)
        return documents, (time.perf_counter() - started) * 1000

    @staticmethod
    def _empty_result(
        *, query: str, strategy: RetrievalStrategy, reason: str
    ) -> RetrievalResult:
        return RetrievalResult(
            query=query,
            documents=[],
            strategy=strategy,
            low_confidence=True,
            confidence_reasons=[reason],
            diagnostics=RetrievalDiagnostics(returned_count=0),
        )


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
