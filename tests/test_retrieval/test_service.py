"""Tests for the deterministic fake retrieval service."""

from __future__ import annotations

import pytest

from agent.retrieval.models import RetrievedDocument
from agent.retrieval.protocols import RetrievalService
from agent.retrieval.service import FakeRetrievalService


def _document(index: int) -> RetrievedDocument:
    return RetrievedDocument(
        document_id=f"doc-{index}",
        title=f"Document {index}",
        content=f"Content {index}",
        metadata={"index": index},
    )


def test_fake_service_matches_retrieval_protocol():
    service: RetrievalService = FakeRetrievalService()
    assert isinstance(service, FakeRetrievalService)


async def test_fake_service_normalizes_query_and_assigns_final_rank():
    original = [_document(1), _document(2)]
    service = FakeRetrievalService({"  Password   RESET ": original})

    result = await service.retrieve(
        "password reset",
        strategy="vector_only",
        top_k=2,
    )

    assert [document.document_id for document in result.documents] == [
        "doc-1",
        "doc-2",
    ]
    assert [document.final_rank for document in result.documents] == [1, 2]
    assert result.strategy == "vector_only"
    assert result.low_confidence is False
    assert result.diagnostics.returned_count == 2


async def test_fake_service_respects_top_k():
    service = FakeRetrievalService(
        {"question": [_document(1), _document(2), _document(3)]}
    )

    result = await service.retrieve("question", top_k=2)

    assert [document.document_id for document in result.documents] == [
        "doc-1",
        "doc-2",
    ]


async def test_fake_service_does_not_mutate_source_documents():
    source = _document(1)
    service = FakeRetrievalService({"question": [source]})

    result = await service.retrieve("question")
    result.documents[0].metadata["changed"] = True

    assert source.final_rank is None
    assert "changed" not in source.metadata


async def test_fake_service_uses_default_documents_for_unknown_query():
    service = FakeRetrievalService(default_documents=[_document(1)])

    result = await service.retrieve("unknown query")

    assert result.documents[0].document_id == "doc-1"


@pytest.mark.parametrize(
    "query,expected_reason",
    [
        ("   ", "empty_query"),
        ("unknown query", "no_retrieval_results"),
    ],
)
async def test_fake_service_returns_explicit_low_confidence_empty_result(
    query,
    expected_reason,
):
    result = await FakeRetrievalService().retrieve(query)

    assert result.documents == []
    assert result.low_confidence is True
    assert result.confidence_reasons == [expected_reason]
    assert result.diagnostics.returned_count == 0


async def test_fake_service_rejects_unknown_strategy():
    with pytest.raises(ValueError, match="Unsupported retrieval strategy"):
        await FakeRetrievalService().retrieve("query", strategy="unknown")


@pytest.mark.parametrize("top_k", [0, 101])
async def test_fake_service_rejects_invalid_top_k(top_k):
    with pytest.raises(ValueError, match="between 1 and 100"):
        await FakeRetrievalService().retrieve("query", top_k=top_k)
