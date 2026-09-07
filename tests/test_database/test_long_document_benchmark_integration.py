"""Opt-in real PostgreSQL check; fake vectors, no network model calls or quality claims."""

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from database.knowledge_ingestion import insert_source
from database.pool import _init_connection
from evals.long_document_eval import execute_live
from evals.long_document_labels import load_benchmark

pytestmark = pytest.mark.skipif(not os.environ.get("CHUNK_TEST_DSN"),
                                reason="requires an EMPTY disposable PostgreSQL database")


@pytest.mark.parametrize("variant", ["whole", "chunked"])
async def test_real_corpus_provenance_and_hybrid_scoring_with_fake_embeddings(monkeypatch, variant):
    import asyncpg
    import openai
    from evals import long_document_eval as runner

    connection = await asyncpg.connect(os.environ["CHUNK_TEST_DSN"])
    try:
        assert await connection.fetchval("SELECT to_regclass('knowledge_base')") is None, "empty DB required"
        transaction = connection.transaction()
        await transaction.start()
        try:
            for name in ("001_initial_schema.sql", "003_knowledge_chunk_provenance.sql"):
                sql = (Path("database/migrations") / name).read_text(encoding="utf-8")
                await connection.execute(sql.replace("BEGIN;", "").replace("COMMIT;", ""))
            await _init_connection(connection)
            pool = MagicMock()
            pool.acquire.return_value.__aenter__ = AsyncMock(return_value=connection)
            pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
            pool.close = AsyncMock()
            benchmark = load_benchmark(variant=variant)
            for source, rows in benchmark.imports:
                await insert_source(pool, source, [{**row, "embedding": [1.] + [0.] * 1535} for row in rows])
            monkeypatch.setattr(runner, "create_pool", AsyncMock(return_value=pool))
            for name in ("LONG_DOCUMENT_EVAL_DATABASE_URL", "DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL"):
                monkeypatch.setenv(name, "test-placeholder")
            monkeypatch.delenv("QWEN_EMBEDDING_MODEL", raising=False)
            monkeypatch.delenv("EMBEDDING_DIMENSIONS", raising=False)
            client = MagicMock()
            client.embeddings.create = AsyncMock(return_value=SimpleNamespace(data=[
                SimpleNamespace(embedding=[1.] + [0.] * 1535)]))
            context = MagicMock()
            context.__aenter__ = AsyncMock(return_value=client)
            context.__aexit__ = AsyncMock(return_value=False)
            monkeypatch.setattr(openai, "AsyncOpenAI", MagicMock(return_value=context))
            report = await execute_live(benchmark, action="evaluate", strategy="hybrid", threshold=.43, top_k=3)
            assert report["raw_metrics"]["successful_cases"] == 36
            assert report["raw_metrics"]["operational_failure_count"] == 0
            assert report["document_count"] == len(benchmark.documents)
            assert client.embeddings.create.await_count == 36
            assert all(set(row["retrieved_source_ids"]) <= set(benchmark.sources) for row in report["case_results"])
        finally:
            await transaction.rollback()
        assert await connection.fetchval("SELECT to_regclass('knowledge_base')") is None
    finally:
        await connection.close()
