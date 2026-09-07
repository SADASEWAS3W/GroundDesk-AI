"""Run SQL migration files against the database using asyncpg.

Usage:
    python -m database.migrations.run_migration
"""

from __future__ import annotations

import asyncio
import argparse
import logging
import os
from pathlib import Path

import asyncpg

logger = logging.getLogger(__name__)


async def run(dsn: str | None = None, *, migration: str = "001_initial_schema.sql") -> None:
    dsn = dsn or os.environ["DATABASE_URL"]
    allowed = {"001_initial_schema.sql", "003_knowledge_chunk_provenance.sql"}
    if migration not in allowed:
        raise ValueError("unsupported migration")
    sql_file = Path(__file__).parent / migration
    sql = sql_file.read_text(encoding="utf-8")

    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(sql)
        logger.info("Migration applied: %s", sql_file.name)

        # Verify tables
        rows = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        )
        tables = [r["tablename"] for r in rows]
        print(f"Tables created ({len(tables)}): {', '.join(tables)}")
    finally:
        await conn.close()


async def main() -> None:
    from dotenv import load_dotenv

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--migration", default="001_initial_schema.sql", choices=[
        "001_initial_schema.sql", "003_knowledge_chunk_provenance.sql",
    ])
    args = parser.parse_args()
    load_dotenv()
    logging.basicConfig(level=logging.INFO)
    await run(migration=args.migration)


if __name__ == "__main__":
    asyncio.run(main())
