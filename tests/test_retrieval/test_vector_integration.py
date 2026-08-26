"""Opt-in integration test for Qwen embeddings and PostgreSQL/pgvector."""

from __future__ import annotations

import os

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_RETRIEVAL_INTEGRATION") != "1",
    reason="set RUN_RETRIEVAL_INTEGRATION=1 to use live provider and database",
)


async def test_pgvector_retriever_returns_real_knowledge_base_documents():
    """Exercise the real provider and database only when explicitly enabled."""
    asyncpg = pytest.importorskip("asyncpg")
    pytest.importorskip("openai")
    assert asyncpg is not None

    from openai import AsyncOpenAI

    from agent.retrieval import PgVectorRetriever
    from database.pool import create_pool

    required = ("DATABASE_URL", "DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        pytest.skip(f"missing integration configuration: {', '.join(missing)}")

    pool = await create_pool(dsn=os.environ["DATABASE_URL"], min_size=1, max_size=2)
    client = AsyncOpenAI(
        api_key=os.environ["DASHSCOPE_API_KEY"],
        base_url=os.environ["DASHSCOPE_BASE_URL"],
    )
    retriever = PgVectorRetriever(model_client=client, db_pool=pool)

    try:
        documents = await retriever.search("How do I reset my password?", top_k=10)
    finally:
        await pool.close()

    assert documents
    assert len(documents) <= 10
    assert [document.vector_rank for document in documents] == list(
        range(1, len(documents) + 1)
    )
    assert all(document.document_id for document in documents)
    assert all(document.vector_score is not None for document in documents)
