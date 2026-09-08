"""Redis-backed guards for duplicate and excessive API requests."""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
from dataclasses import dataclass

import redis.asyncio as redis
from redis.exceptions import WatchError

logger = logging.getLogger(__name__)

IDEMPOTENCY_TTL_SECONDS = 3600
REVIEW_LOCK_TTL_SECONDS = 60


def _positive_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


CHAT_RATE_LIMIT_REQUESTS = _positive_env("CHAT_RATE_LIMIT_REQUESTS", 6)
CHAT_RATE_LIMIT_WINDOW_SECONDS = _positive_env(
    "CHAT_RATE_LIMIT_WINDOW_SECONDS",
    60,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _key(namespace: str, value: str) -> str:
    return f"crm:{namespace}:{_digest(value)}"


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after: int = 0


async def get_idempotent_job(
    redis_client: redis.Redis | None,
    idempotency_key: str,
) -> str | None:
    """Return the job claimed by an idempotency key, if available."""
    if redis_client is None:
        return None
    try:
        value = await redis_client.get(_key("idempotency:chat", idempotency_key))
        return value if isinstance(value, str) and value else None
    except Exception:
        logger.warning("Idempotency lookup failed", exc_info=True)
        return None


async def claim_idempotent_job(
    redis_client: redis.Redis | None,
    idempotency_key: str,
    job_id: str,
) -> tuple[bool, str | None]:
    """Atomically claim a key or return the job that already owns it."""
    if redis_client is None:
        return True, None
    key = _key("idempotency:chat", idempotency_key)
    try:
        claimed = await redis_client.set(
            key,
            job_id,
            ex=IDEMPOTENCY_TTL_SECONDS,
            nx=True,
        )
        if claimed:
            return True, None
        existing = await redis_client.get(key)
        return False, existing if isinstance(existing, str) and existing else None
    except Exception:
        logger.warning("Idempotency claim failed", exc_info=True)
        return True, None


async def release_idempotent_job(
    redis_client: redis.Redis | None,
    idempotency_key: str,
    job_id: str,
) -> None:
    """Release a failed job's claim without deleting a newer owner's claim."""
    if redis_client is None:
        return
    await _release_owned_key(
        redis_client,
        _key("idempotency:chat", idempotency_key),
        job_id,
    )


async def check_chat_rate_limit(
    redis_client: redis.Redis | None,
    identity: str,
) -> RateLimitDecision:
    """Consume one request from a fixed Redis-backed rate-limit window."""
    if redis_client is None:
        return RateLimitDecision(allowed=True)
    key = _key("rate:chat", identity)
    try:
        created = await redis_client.set(
            key,
            1,
            ex=CHAT_RATE_LIMIT_WINDOW_SECONDS,
            nx=True,
        )
        count = 1 if created else int(await redis_client.incr(key))
        if count <= CHAT_RATE_LIMIT_REQUESTS:
            return RateLimitDecision(allowed=True)
        ttl = int(await redis_client.ttl(key))
        retry_after = ttl if ttl > 0 else CHAT_RATE_LIMIT_WINDOW_SECONDS
        return RateLimitDecision(allowed=False, retry_after=retry_after)
    except Exception:
        logger.warning("Chat rate-limit check failed", exc_info=True)
        return RateLimitDecision(allowed=True)


async def acquire_review_lock(
    redis_client: redis.Redis | None,
    run_id: str,
) -> tuple[bool, str | None]:
    """Claim a short distributed lock for one review operation."""
    if redis_client is None:
        return True, None
    owner_id = secrets.token_urlsafe(24)
    try:
        acquired = await redis_client.set(
            _key("lock:review", run_id),
            owner_id,
            ex=REVIEW_LOCK_TTL_SECONDS,
            nx=True,
        )
        return bool(acquired), owner_id if acquired else None
    except Exception:
        logger.warning("Review lock acquisition failed", exc_info=True)
        return True, None


async def release_review_lock(
    redis_client: redis.Redis | None,
    run_id: str,
    owner_id: str | None,
) -> None:
    """Release a review lock only when it is still owned by this request."""
    if redis_client is None or owner_id is None:
        return
    await _release_owned_key(redis_client, _key("lock:review", run_id), owner_id)


async def _release_owned_key(
    redis_client: redis.Redis,
    key: str,
    owner: str,
) -> None:
    for _ in range(3):
        try:
            async with redis_client.pipeline(transaction=True) as pipeline:
                await pipeline.watch(key)
                if await pipeline.get(key) != owner:
                    await pipeline.unwatch()
                    return
                pipeline.multi()
                pipeline.delete(key)
                await pipeline.execute()
                return
        except WatchError:
            continue
        except Exception:
            logger.warning("Review lock release failed", exc_info=True)
            return
    logger.warning("Review lock release lost repeated ownership races")
