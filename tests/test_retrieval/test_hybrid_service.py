"""Tests for the stage-four hybrid retrieval service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.retrieval import (
    HybridRetrievalService,
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


def _service(vector_documents=(), bm25_documents=()):
    vector = MagicMock()
    vector.search = AsyncMock(return_value=list(vector_documents))
    bm25 = MagicMock()
    bm25.search = AsyncMock(return_value=list(bm25_documents))
    service = HybridRetrievalService(
        vector_retriever=vector,
        bm25_retriever=bm25,
        fusion_strategy=ReciprocalRankFusion(),
    )
    return service, vector, bm25


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

    with pytest.raises(RetrievalCapabilityError, match="stage five"):
        await service.retrieve("query", strategy="hybrid_rerank", top_k=3)

    vector.search.assert_not_awaited()
    bm25.search.assert_not_awaited()
