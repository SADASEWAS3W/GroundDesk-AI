"""Opt-in PostgreSQL integration test without an external model call."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_PGVECTOR_INTEGRATION") != "1",
    reason="set RUN_PGVECTOR_INTEGRATION=1 with DATABASE_URL to test pgvector",
)


async def test_pgvector_query_returns_the_document_used_as_query_vector():
    """Use a stored vector as the query so no paid provider call is required."""
    pytest.importorskip("asyncpg")

    from agent.retrieval import PgVectorRetriever
    from database.pool import create_pool

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        pytest.skip("DATABASE_URL is required for pgvector integration")

    pool = await create_pool(dsn=dsn, min_size=1, max_size=2)
    try:
        async with pool.acquire() as connection:
            source = await connection.fetchrow(
                "SELECT id, embedding FROM knowledge_base "
                "WHERE embedding IS NOT NULL ORDER BY id LIMIT 1"
            )
        if source is None:
            pytest.skip("knowledge_base has no embedded documents")

        embedding_response = MagicMock()
        embedding_item = MagicMock()
        embedding_item.embedding = source["embedding"]
        embedding_response.data = [embedding_item]
        model_client = MagicMock()
        model_client.embeddings.create = AsyncMock(return_value=embedding_response)

        retriever = PgVectorRetriever(model_client=model_client, db_pool=pool)
        documents = await retriever.search("integration probe", top_k=10)
    finally:
        await pool.close()

    assert documents
    assert documents[0].document_id == str(source["id"])
    assert documents[0].vector_rank == 1
    assert documents[0].vector_score == pytest.approx(1.0, abs=1e-5)


async def test_real_knowledge_corpus_builds_and_searches_with_bm25():
    """Load the database corpus and verify it is searchable without a model."""
    pytest.importorskip("asyncpg")

    from agent.retrieval import InMemoryBM25Retriever, load_knowledge_documents
    from database.pool import create_pool

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        pytest.skip("DATABASE_URL is required for pgvector integration")

    pool = await create_pool(dsn=dsn, min_size=1, max_size=2)
    try:
        documents = await load_knowledge_documents(pool)
    finally:
        await pool.close()

    if not documents:
        pytest.skip("knowledge_base is empty")

    retriever = InMemoryBM25Retriever()
    status = retriever.build(documents)
    results = await retriever.search(documents[0].title, top_k=100)

    assert status.document_count == len(documents)
    assert documents[0].document_id in {
        document.document_id for document in results
    }
