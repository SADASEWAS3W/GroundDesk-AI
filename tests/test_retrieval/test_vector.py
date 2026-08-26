"""Tests for the independent PostgreSQL/pgvector retriever."""

from __future__ import annotations

import math
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.retrieval import (
    EMBEDDING_DIMENSIONS,
    PgVectorRetriever,
    VectorRetrievalError,
)


class _AsyncContextManager:
    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, *args):
        return False


def _dependencies():
    embedding = MagicMock()
    embedding.embedding = [0.01] * EMBEDDING_DIMENSIONS
    response = MagicMock()
    response.data = [embedding]
    model_client = MagicMock()
    model_client.embeddings.create = AsyncMock(return_value=response)

    connection = AsyncMock()
    connection.transaction = MagicMock(return_value=_AsyncContextManager(None))
    pool = MagicMock()
    pool.acquire.return_value = _AsyncContextManager(connection)
    return model_client, pool, connection


async def test_search_returns_stable_ranked_documents():
    model_client, pool, connection = _dependencies()
    document_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
    connection.fetch.return_value = [
        {
            "id": document_id,
            "title": "Password Reset",
            "content": "Open Settings and choose Reset Password.",
            "category": "account-management",
            "distance": 0.18,
            "similarity": 0.82,
        }
    ]
    retriever = PgVectorRetriever(model_client=model_client, db_pool=pool)

    documents = await retriever.search("  reset   my password  ", top_k=10)

    assert len(documents) == 1
    document = documents[0]
    assert document.document_id == str(document_id)
    assert document.vector_score == pytest.approx(0.82)
    assert document.vector_rank == 1
    assert document.source_retrievers == ("vector",)
    assert document.metadata == {
        "source": "knowledge_base",
        "vector_distance": pytest.approx(0.18),
    }
    model_client.embeddings.create.assert_awaited_once_with(
        input="reset my password",
        model="text-embedding-v4",
        dimensions=1536,
        encoding_format="float",
    )
    connection.execute.assert_awaited_once_with(
        "SELECT set_config('ivfflat.probes', $1, true)", "10"
    )
    sql, embedding_parameter, limit_parameter = connection.fetch.await_args.args
    assert "embedding <=> $1::vector" in sql
    assert "ORDER BY embedding <=> $1::vector" in sql
    assert "LIMIT $2" in sql
    assert len(embedding_parameter) == EMBEDDING_DIMENSIONS
    assert limit_parameter == 10


async def test_explicit_threshold_is_parameterized_for_baseline_comparison():
    model_client, pool, connection = _dependencies()
    connection.fetch.return_value = []
    retriever = PgVectorRetriever(
        model_client=model_client,
        db_pool=pool,
        similarity_threshold=0.25,
    )

    assert await retriever.search("quantum computing", top_k=3) == []

    sql, _, threshold_parameter, limit_parameter = connection.fetch.await_args.args
    assert "similarity" in sql
    assert ">= $2" in sql
    assert "LIMIT $3" in sql
    assert threshold_parameter == 0.25
    assert limit_parameter == 3


async def test_empty_query_returns_no_documents_without_external_calls():
    model_client, pool, _ = _dependencies()
    retriever = PgVectorRetriever(model_client=model_client, db_pool=pool)

    assert await retriever.search(" \t ", top_k=10) == []
    model_client.embeddings.create.assert_not_awaited()
    pool.acquire.assert_not_called()


@pytest.mark.parametrize("top_k", [0, -1, 101, True, 1.5])
async def test_invalid_top_k_is_rejected(top_k):
    model_client, pool, _ = _dependencies()
    retriever = PgVectorRetriever(model_client=model_client, db_pool=pool)

    with pytest.raises((TypeError, ValueError)):
        await retriever.search("query", top_k=top_k)


async def test_wrong_embedding_dimensions_never_query_database():
    model_client, pool, _ = _dependencies()
    model_client.embeddings.create.return_value.data[0].embedding = [0.1] * 1024
    retriever = PgVectorRetriever(model_client=model_client, db_pool=pool)

    with pytest.raises(VectorRetrievalError, match="dimension mismatch"):
        await retriever.search("query")

    pool.acquire.assert_not_called()


async def test_non_finite_embedding_never_queries_database():
    model_client, pool, _ = _dependencies()
    values = [0.1] * EMBEDDING_DIMENSIONS
    values[-1] = math.nan
    model_client.embeddings.create.return_value.data[0].embedding = values
    retriever = PgVectorRetriever(model_client=model_client, db_pool=pool)

    with pytest.raises(VectorRetrievalError, match="non-finite"):
        await retriever.search("query")

    pool.acquire.assert_not_called()


async def test_embedding_provider_error_is_distinct_from_empty_results():
    model_client, pool, _ = _dependencies()
    model_client.embeddings.create.side_effect = RuntimeError("provider down")
    retriever = PgVectorRetriever(model_client=model_client, db_pool=pool)

    with pytest.raises(VectorRetrievalError, match="embedding failed"):
        await retriever.search("query")


async def test_database_error_is_distinct_from_empty_results():
    model_client, pool, connection = _dependencies()
    connection.fetch.side_effect = RuntimeError("database down")
    retriever = PgVectorRetriever(model_client=model_client, db_pool=pool)

    with pytest.raises(VectorRetrievalError, match="pgvector query failed"):
        await retriever.search("query")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"embedding_dimensions": 1024}, "must be 1536"),
        ({"embedding_model": "  "}, "must not be empty"),
        ({"similarity_threshold": 1.1}, "between -1 and 1"),
        ({"ivfflat_probes": 0}, "positive integer"),
    ],
)
def test_invalid_configuration_is_rejected(kwargs, message):
    model_client, pool, _ = _dependencies()

    with pytest.raises(ValueError, match=message):
        PgVectorRetriever(model_client=model_client, db_pool=pool, **kwargs)
