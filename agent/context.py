"""Shared agent context injected into every @function_tool via RunContextWrapper."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import asyncpg
import redis.asyncio as redis
from openai import AsyncOpenAI

from agent.cache import create_redis_client
from database.pool import create_pool


@dataclass
class AgentContext:
    """Holds the DB pool, model client, and Redis client shared across all tools.

    Passed to tools via ``RunContextWrapper[AgentContext]`` — the SDK
    injects it automatically; it is never sent to the LLM.
    """

    db_pool: asyncpg.Pool
    model_client: AsyncOpenAI
    redis_client: redis.Redis | None = field(default=None)


async def build_context(
    *,
    dsn: str | None = None,
    dashscope_api_key: str | None = None,
    dashscope_base_url: str | None = None,
    redis_url: str | None = None,
) -> AgentContext:
    """Create an AgentContext from environment variables (or explicit args).

    Parameters
    ----------
    dsn:
        PostgreSQL DSN.  Falls back to ``DATABASE_URL`` env var.
    dashscope_api_key:
        Alibaba Cloud Model Studio key. Falls back to ``DASHSCOPE_API_KEY``.
    dashscope_base_url:
        OpenAI-compatible endpoint. Falls back to ``DASHSCOPE_BASE_URL``.
    redis_url:
        Redis connection URL.  Falls back to ``REDIS_URL`` env var,
        then ``redis://localhost:6379``.
    """
    api_key = dashscope_api_key or os.environ.get("DASHSCOPE_API_KEY")
    base_url = dashscope_base_url or os.environ.get("DASHSCOPE_BASE_URL")
    if not api_key:
        raise RuntimeError("DASHSCOPE_API_KEY is required")
    if not base_url:
        raise RuntimeError("DASHSCOPE_BASE_URL is required")

    pool = await create_pool(dsn=dsn)
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    rclient = await create_redis_client(url=redis_url)
    return AgentContext(db_pool=pool, model_client=client, redis_client=rclient)
