"""Tests for NoOp and provider-backed rerankers."""

from __future__ import annotations

import json
import math
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.retrieval import (
    LLMReranker,
    NoOpReranker,
    RerankerProviderError,
    RerankerResponseError,
    RetrievedDocument,
)


def _document(number: int, *, content: str | None = None) -> RetrievedDocument:
    return RetrievedDocument(
        document_id=f"doc-{number}",
        title=f"Document {number}",
        content=content or f"Content {number}",
        rrf_score=1 / (60 + number),
        final_rank=number,
    )


def _model_client(rankings):
    message = MagicMock()
    message.content = json.dumps({"rankings": rankings})
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response)
    return client


async def test_noop_reranker_preserves_order_and_limits_results():
    documents = [_document(1), _document(2), _document(3)]

    results = await NoOpReranker().rerank("query", documents, top_k=2)

    assert [document.document_id for document in results] == ["doc-1", "doc-2"]
    assert [document.final_rank for document in results] == [1, 2]
    assert all(document.rerank_score is not None for document in results)


async def test_llm_reranker_orders_by_validated_scores():
    client = _model_client(
        [
            {"document_id": "doc-1", "score": 0.2},
            {"document_id": "doc-2", "score": 0.9},
            {"document_id": "doc-3", "score": 0.5},
        ]
    )
    reranker = LLMReranker(model_client=client)

    results = await reranker.rerank(
        "password reset",
        [_document(1), _document(2), _document(3)],
        top_k=2,
    )

    assert [document.document_id for document in results] == ["doc-2", "doc-3"]
    assert [document.rerank_score for document in results] == [0.9, 0.5]
    assert [document.final_rank for document in results] == [1, 2]
    call = client.chat.completions.create.await_args.kwargs
    assert call["model"] == "qwen-plus"
    assert call["temperature"] == 0
    assert call["response_format"] == {"type": "json_object"}


async def test_prompt_truncates_query_and_document_content():
    client = _model_client([{"document_id": "doc-1", "score": 0.8}])
    reranker = LLMReranker(
        model_client=client,
        max_query_chars=5,
        max_document_chars=7,
    )

    await reranker.rerank("123456789", [_document(1, content="abcdefghijk")], top_k=1)

    user_payload = json.loads(
        client.chat.completions.create.await_args.kwargs["messages"][1]["content"]
    )
    assert user_payload["query"] == "12345"
    assert user_payload["candidates"][0]["content"] == "abcdefg"


@pytest.mark.parametrize(
    "rankings",
    [
        [{"document_id": "unknown", "score": 0.9}],
        [
            {"document_id": "doc-1", "score": 0.9},
            {"document_id": "doc-1", "score": 0.8},
        ],
        [{"document_id": "doc-1"}],
        [{"document_id": "doc-1", "score": math.nan}],
        [{"document_id": "doc-1", "score": 1.1}],
    ],
)
async def test_invalid_or_incomplete_rankings_are_rejected(rankings):
    reranker = LLMReranker(model_client=_model_client(rankings))

    with pytest.raises(RerankerResponseError):
        await reranker.rerank("query", [_document(1), _document(2)], top_k=2)


async def test_malformed_json_is_rejected():
    client = _model_client([])
    client.chat.completions.create.return_value.choices[0].message.content = "not-json"

    with pytest.raises(RerankerResponseError, match="valid JSON"):
        await LLMReranker(model_client=client).rerank(
            "query", [_document(1)], top_k=1
        )


async def test_provider_failure_has_a_distinct_error():
    client = _model_client([])
    client.chat.completions.create.side_effect = RuntimeError("provider down")

    with pytest.raises(RerankerProviderError):
        await LLMReranker(model_client=client).rerank(
            "query", [_document(1)], top_k=1
        )


async def test_candidate_limit_is_enforced_before_provider_call():
    client = _model_client([])
    reranker = LLMReranker(model_client=client, max_candidates=1)

    with pytest.raises(ValueError, match="at most 1"):
        await reranker.rerank("query", [_document(1), _document(2)], top_k=1)

    client.chat.completions.create.assert_not_awaited()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"model": " "},
        {"max_candidates": 0},
        {"max_document_chars": True},
        {"max_query_chars": -1},
    ],
)
def test_invalid_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        LLMReranker(model_client=_model_client([]), **kwargs)
