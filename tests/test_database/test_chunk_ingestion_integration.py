"""Opt-in disposable PostgreSQL test. All schema/data changes roll back."""

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.retrieval.ingest import prepare_source
from database.knowledge_ingestion import insert_source
from database.pool import _init_connection

pytestmark = pytest.mark.skipif(not os.environ.get("CHUNK_TEST_DSN"),
                                reason="set CHUNK_TEST_DSN to an EMPTY disposable PostgreSQL database")


@pytest.mark.parametrize("legacy", [False, True])
async def test_migration_import_idempotency_retrieval_and_rollback(legacy):
    import asyncpg
    from agent.retrieval.vector import PgVectorRetriever

    conn = await asyncpg.connect(os.environ["CHUNK_TEST_DSN"])
    try:
        assert await conn.fetchval("SELECT to_regclass('knowledge_base')") is None, "test requires empty database"
        outer = conn.transaction()
        await outer.start()
        try:
            root = Path("database/migrations")
            def sql(name):
                return (root / name).read_text(encoding="utf-8").replace("BEGIN;", "").replace("COMMIT;", "")
            await conn.execute(sql("001_initial_schema.sql"))
            await _init_connection(conn)
            if legacy:
                await conn.execute("INSERT INTO knowledge_base(title,content,category) VALUES ('Legacy','Keep me','help')")
            migration = sql("003_knowledge_chunk_provenance.sql")
            await conn.execute(migration)
            await conn.execute(migration)
            pool = MagicMock()
            pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
            pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
            source, rows = prepare_source("密码重置说明。" * 30, source_id="fixture-v1", title="Password",
                                          category="help", chunk_size=80, overlap=10)
            rows = [{**row, "embedding": [1.] + [0.] * 1535} for row in rows]
            assert await insert_source(pool, source, rows) is True
            assert await insert_source(pool, source, rows) is False
            with pytest.raises(ValueError, match="different"):
                await insert_source(pool, {**source, "content_sha256": "changed"}, rows)
            assert await conn.fetchval("SELECT count(*) FROM knowledge_base") == len(rows) + int(legacy)
            client = MagicMock()
            client.embeddings.create = AsyncMock(return_value=SimpleNamespace(data=[
                SimpleNamespace(embedding=rows[0]["embedding"])
            ]))
            found = await PgVectorRetriever(model_client=client, db_pool=pool).search("密码", top_k=3)
            assert found and all(doc.document_id in {str(row["id"]) for row in rows} for doc in found)
            linked = await conn.fetchval("SELECT source_id FROM knowledge_chunk_provenance WHERE chunk_id=$1", rows[0]["id"])
            assert linked == source["source_id"]
            # A failure after the first insert must roll back the source and all chunks.
            other, broken = prepare_source("x" * 200, source_id="broken", title="Broken", category="help",
                                           chunk_size=80, overlap=10)
            broken = [{**row, "embedding": [1.] * 1536} for row in broken]
            broken[1]["embedding"] = [1.] * 10
            with pytest.raises(asyncpg.PostgresError):
                await insert_source(pool, other, broken)
            assert await conn.fetchval("SELECT count(*) FROM knowledge_sources WHERE source_id='broken'") == 0
            assert await conn.fetchval("SELECT count(*) FROM knowledge_base") == len(rows) + int(legacy)
        finally:
            await outer.rollback()
    finally:
        await conn.close()
