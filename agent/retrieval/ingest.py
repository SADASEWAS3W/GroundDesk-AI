"""Preview UTF-8 text/Markdown chunks; optionally embed and atomically import."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from agent.retrieval.chunking import CHUNKING_VERSION, split_document
from agent.retrieval.vector import DEFAULT_EMBEDDING_MODEL, EMBEDDING_DIMENSIONS
from database.knowledge_ingestion import insert_source


def prepare_source(content: str, *, source_id: str, title: str, category: str,
                   chunk_size: int = 1200, overlap: int = 150) -> tuple[dict, list[dict]]:
    for name, value in (("source_id", source_id), ("title", title), ("category", category)):
        if not value.strip():
            raise ValueError(f"{name} must not be blank")
    if len(category) > 50:
        raise ValueError("category must fit VARCHAR(50)")
    chunks = split_document(content, chunk_size=chunk_size, overlap=overlap)
    if not chunks:
        raise ValueError("source has no non-whitespace content")
    source = dict(
        source_id=source_id, title=title, category=category,
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        chunking_version=CHUNKING_VERSION, chunk_size=chunk_size, overlap=overlap,
        embedding_model=DEFAULT_EMBEDDING_MODEL, embedding_dimensions=EMBEDDING_DIMENSIONS,
    )
    rows = []
    for chunk in chunks:
        identity = json.dumps([source, chunk.index], sort_keys=True, ensure_ascii=False)
        chunk_id = uuid5(NAMESPACE_URL, identity)
        suffix = f" [chunk {chunk.index + 1}; {chunk_id}]"
        rows.append(dict(
            id=chunk_id, title=title[:255 - len(suffix)] + suffix,
            content=chunk.content, index=chunk.index, start=chunk.start, end=chunk.end,
        ))
    return source, rows


async def embed_chunks(client, source: dict, rows: list[dict]) -> list[dict]:
    """Validate complete batches before returning anything that can be persisted."""
    embedded = []
    for start in range(0, len(rows), 10):
        batch = rows[start:start + 10]
        result = await client.embeddings.create(
            input=[f"{source['title']}\n\n{row['content']}" for row in batch],
            model=DEFAULT_EMBEDDING_MODEL, dimensions=EMBEDDING_DIMENSIONS,
            encoding_format="float",
        )
        indexed = {item.index: item.embedding for item in result.data}
        if len(result.data) != len(batch) or set(indexed) != set(range(len(batch))):
            raise ValueError("embedding response count or indices do not match input")
        for index, row in enumerate(batch):
            vector = indexed[index]
            if len(vector) != EMBEDDING_DIMENSIONS or any(
                isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) for value in vector
            ):
                raise ValueError("embedding must contain 1536 finite numbers")
            embedded.append({**row, "embedding": vector})
    return embedded


async def execute_import(source: dict, rows: list[dict]) -> bool:
    from openai import AsyncOpenAI
    from database.pool import create_pool

    for name in ("DATABASE_URL", "DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL"):
        if not os.environ.get(name):
            raise ValueError(f"{name} is required for live import")
    if os.environ.get("QWEN_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL) != DEFAULT_EMBEDDING_MODEL:
        raise ValueError("embedding model differs from the current retrieval contract")
    if os.environ.get("EMBEDDING_DIMENSIONS", "1536") != "1536":
        raise ValueError("EMBEDDING_DIMENSIONS must be 1536")
    pool = await create_pool(min_size=1, max_size=2)
    try:
        async with pool.acquire() as conn:
            if not await conn.fetchval("SELECT to_regclass('public.knowledge_chunk_provenance')"):
                raise ValueError("apply migration 003 before live import")
        async with AsyncOpenAI(
            api_key=os.environ["DASHSCOPE_API_KEY"],
            base_url=os.environ["DASHSCOPE_BASE_URL"], max_retries=0, timeout=30,
        ) as client:
            embedded = await embed_chunks(client, source, rows)
        return await insert_source(pool, source, embedded)
    finally:
        await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--source-id", required=True, help="stable logical source ID, not a private path")
    parser.add_argument("--title", required=True)
    parser.add_argument("--category", default="documentation")
    parser.add_argument("--chunk-size", type=int, default=1200)
    parser.add_argument("--overlap", type=int, default=150)
    parser.add_argument("--execute-live", action="store_true", help="authorize provider calls AND database inserts")
    args = parser.parse_args()
    source, rows = prepare_source(
        args.path.read_text(encoding="utf-8-sig"), source_id=args.source_id,
        title=args.title, category=args.category, chunk_size=args.chunk_size, overlap=args.overlap,
    )
    if args.execute_live:
        from dotenv import load_dotenv
        load_dotenv()
        print("Imported" if asyncio.run(execute_import(source, rows)) else "Already imported")
    else:
        print(json.dumps({"mode": "preview", "source": source, "chunk_count": len(rows),
                          "chunks": rows}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
