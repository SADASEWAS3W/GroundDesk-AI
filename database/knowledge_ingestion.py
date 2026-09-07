"""Atomic insert-only persistence of a source and its searchable chunks."""

from __future__ import annotations

from typing import Any


async def insert_source(pool: Any, source: dict, rows: list[dict]) -> bool:
    """Return False for identical imports; reject changed source IDs without deletion."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            inserted = await conn.fetchval(
                """INSERT INTO knowledge_sources
                (source_id, title, category, content_sha256, chunking_version,
                 chunk_size, overlap, embedding_model, embedding_dimensions)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                ON CONFLICT (source_id) DO NOTHING RETURNING source_id""",
                *(source[key] for key in (
                    "source_id", "title", "category", "content_sha256", "chunking_version",
                    "chunk_size", "overlap", "embedding_model", "embedding_dimensions",
                )),
            )
            if inserted is None:
                existing = await conn.fetchrow(
                    "SELECT * FROM knowledge_sources WHERE source_id=$1", source["source_id"]
                )
                count = await conn.fetchval(
                    "SELECT count(*) FROM knowledge_chunk_provenance WHERE source_id=$1",
                    source["source_id"],
                )
                if any(existing[key] != value for key, value in source.items()) or count != len(rows):
                    raise ValueError("source_id already exists with different content/configuration or incomplete chunks")
                return False
            for row in rows:
                await conn.execute(
                    """INSERT INTO knowledge_base (id,title,content,category,embedding)
                    VALUES ($1,$2,$3,$4,$5)""",
                    row["id"], row["title"], row["content"], source["category"], row["embedding"],
                )
                await conn.execute(
                    """INSERT INTO knowledge_chunk_provenance
                    (chunk_id,source_id,chunk_index,start_offset,end_offset)
                    VALUES ($1,$2,$3,$4,$5)""",
                    row["id"], source["source_id"], row["index"], row["start"], row["end"],
                )
    return True
