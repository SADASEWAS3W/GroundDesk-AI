"""Tests for the stage-four hybrid retrieval service."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.retrieval import (
    HybridRetrievalService,
    RetrievalConfidencePolicy,
    RerankerProviderError,
    ReciprocalRankFusion,
    RetrievalCapabilityError,
    RetrievedDocument,
)


def _document(document_id: str, *, source: str) -> RetrievedDocument:
    return RetrievedDocument(
        document_id=document_id,
        title=f"Title {document_id}",
        content=f"Content {document_id}",
        source_retrievers=(source,),
        vector_score=0.8 if source == "vector" else None,
        vector_rank=1 if source == "vector" else None,
        bm25_score=2.0 if source == "bm25" else None,
        bm25_rank=1 if source == "bm25" else None,
    )


def _service(vector_documents=(), bm25_documents=(), *, reranker=None, timeout=10.0):
    vector = MagicMock()
    vector.search = AsyncMock(return_value=list(vector_documents))
    bm25 = MagicMock()
    bm25.search = AsyncMock(return_value=list(bm25_documents))
    service = HybridRetrievalService(
        vector_retriever=vector,
        bm25_retriever=bm25,
        fusion_strategy=ReciprocalRankFusion(),
        reranker=reranker,
        reranker_timeout_seconds=timeout,
    )
    return service, vector, bm25


async def test_eval_calibrated_vector_threshold_marks_weak_result():
    weak = replace(_document("weak", source="vector"), vector_score=0.39)
    service, _, _ = _service([weak])

    result = await service.retrieve("outside knowledge", strategy="vector_only")

    assert result.low_confidence is True
    assert result.confidence_reasons == ["top1_vector_score_below_threshold"]


async def test_vector_threshold_keeps_calibrated_boundary_confident():
    boundary = replace(_document("boundary", source="vector"), vector_score=0.40)
    service, _, _ = _service([boundary])

    result = await service.retrieve("known answer", strategy="vector_only")

    assert result.low_confidence is False
    assert result.confidence_reasons == []


def test_confidence_threshold_can_be_disabled():
    policy = RetrievalConfidencePolicy(min_top1_vector_score=None)

    assert policy.reasons(
        [replace(_document("weak", source="vector"), vector_score=0.1)],
        MagicMock(reranker_fallback=False),
    ) == []


async def test_vector_only_does_not_call_bm25():
    service, vector, bm25 = _service([_document("v", source="vector")])

    result = await service.retrieve("query", strategy="vector_only", top_k=3)

    assert [document.document_id for document in result.documents] == ["v"]
    assert result.documents[0].final_rank == 1
    vector.search.assert_awaited_once_with("query", top_k=3)
    bm25.search.assert_not_awaited()


async def test_hybrid_calls_both_retrievers_and_fuses_results():
    service, vector, bm25 = _service(
        [_document("shared", source="vector")],
        [_document("shared", source="bm25"), _document("keyword", source="bm25")],
    )

    result = await service.retrieve(" mixed query ", strategy="hybrid", top_k=3)

    assert [document.document_id for document in result.documents] == [
        "shared",
        "keyword",
    ]
    assert result.diagnostics.vector_candidate_count == 1
    assert result.diagnostics.bm25_candidate_count == 2
    assert result.diagnostics.fused_candidate_count == 2
    assert result.diagnostics.returned_count == 2
    vector.search.assert_awaited_once_with("mixed query", top_k=10)
    bm25.search.assert_awaited_once_with("mixed query", top_k=10)


async def test_empty_query_returns_low_confidence_without_components():
    service, vector, bm25 = _service()

    result = await service.retrieve("  ", strategy="hybrid", top_k=3)

    assert result.low_confidence is True
    assert result.confidence_reasons == ["empty_query"]
    vector.search.assert_not_awaited()
    bm25.search.assert_not_awaited()


async def test_no_results_returns_structured_low_confidence():
    service, _, _ = _service()

    result = await service.retrieve("unknown", strategy="hybrid", top_k=3)

    assert result.documents == []
    assert result.low_confidence is True
    assert result.confidence_reasons == ["no_retrieval_results"]


async def test_hybrid_rerank_is_not_falsely_reported_as_available():
    service, vector, bm25 = _service()

    with pytest.raises(RetrievalCapabilityError, match="configured reranker"):
        await service.retrieve("query", strategy="hybrid_rerank", top_k=3)

    vector.search.assert_not_awaited()
    bm25.search.assert_not_awaited()


async def test_hybrid_rerank_returns_validated_top_k():
    reranker = MagicMock()

    async def rerank(query, documents, *, top_k):
        return [
            replace(documents[1], rerank_score=0.9),
            replace(documents[0], rerank_score=0.7),
        ][:top_k]

    reranker.rerank = AsyncMock(side_effect=rerank)
    service, _, _ = _service(
        [_document("vector", source="vector")],
        [_document("keyword", source="bm25")],
        reranker=reranker,
    )

    result = await service.retrieve("query", strategy="hybrid_rerank", top_k=2)

    assert [document.document_id for document in result.documents] == [
        "vector",
        "keyword",
    ]
    assert [document.final_rank for document in result.documents] == [1, 2]
    assert result.diagnostics.reranker_fallback is False
    assert result.diagnostics.rerank_latency_ms is not None


@pytest.mark.parametrize(
    ("side_effect", "reason"),
    [
        (RerankerProviderError("down"), "reranker_provider_error"),
        (RuntimeError("unexpected"), "reranker_error"),
    ],
)
async def test_reranker_errors_fall_back_to_rrf(side_effect, reason):
    reranker = MagicMock()
    reranker.rerank = AsyncMock(side_effect=side_effect)
    service, _, _ = _service(
        [_document("vector", source="vector")],
        [_document("keyword", source="bm25")],
        reranker=reranker,
    )

    result = await service.retrieve("query", strategy="hybrid_rerank", top_k=2)

    assert [document.document_id for document in result.documents] == [
        "keyword",
        "vector",
    ]
    assert result.diagnostics.reranker_fallback is True
    assert result.diagnostics.fallback_reason == reason


async def test_invalid_reranker_output_falls_back_to_rrf():
    reranker = MagicMock()
    reranker.rerank = AsyncMock(
        return_value=[
            RetrievedDocument(
                document_id="unknown",
                title="Unknown",
                content="Unknown",
                rerank_score=1.0,
            )
        ]
    )
    service, _, _ = _service(
        [_document("vector", source="vector")],
        [_document("keyword", source="bm25")],
        reranker=reranker,
    )

    result = await service.retrieve("query", strategy="hybrid_rerank", top_k=2)

    assert result.diagnostics.reranker_fallback is True
    assert result.diagnostics.fallback_reason == "reranker_invalid_output"
    assert all(document.rerank_score is None for document in result.documents)


async def test_reranker_timeout_falls_back_to_rrf():
    async def slow_rerank(query, documents, *, top_k):
        await asyncio.sleep(0.05)
        return []

    reranker = MagicMock()
    reranker.rerank = AsyncMock(side_effect=slow_rerank)
    service, _, _ = _service(
        [_document("vector", source="vector")],
        [_document("keyword", source="bm25")],
        reranker=reranker,
        timeout=0.001,
    )

    result = await service.retrieve("query", strategy="hybrid_rerank", top_k=2)

    assert result.diagnostics.reranker_fallback is True
    assert result.diagnostics.fallback_reason == "reranker_timeout"
    assert result.low_confidence is True
    assert result.confidence_reasons == ["reranker_fallback"]


@pytest.mark.parametrize("timeout", [0, -1, True, float("nan"), float("inf")])
def test_invalid_reranker_timeout_is_rejected(timeout):
    with pytest.raises(ValueError, match="must be positive"):
        _service(timeout=timeout)
