"""Review repository abstractions with Redis and in-memory implementations."""

from __future__ import annotations

from typing import Protocol

from agent.review.models import ReviewRecord, RunStatus

_REVIEW_TTL_SECONDS = 24 * 60 * 60
_REVIEW_KEY_PREFIX = "crm:review:"
_PENDING_KEY = "crm:reviews:pending"


class ReviewRepository(Protocol):
    async def save(self, record: ReviewRecord) -> None: ...

    async def get(self, run_id: str) -> ReviewRecord | None: ...

    async def list_pending(self) -> list[ReviewRecord]: ...


class InMemoryReviewRepository:
    """Single-process fallback used when Redis is unavailable and in tests."""

    def __init__(self) -> None:
        self._records: dict[str, ReviewRecord] = {}

    async def save(self, record: ReviewRecord) -> None:
        self._records[record.run_id] = record.model_copy(deep=True)

    async def get(self, run_id: str) -> ReviewRecord | None:
        record = self._records.get(run_id)
        return record.model_copy(deep=True) if record is not None else None

    async def list_pending(self) -> list[ReviewRecord]:
        records = [
            record.model_copy(deep=True)
            for record in self._records.values()
            if record.status == RunStatus.WAITING_REVIEW
        ]
        return sorted(records, key=lambda item: item.created_at)


class RedisReviewRepository:
    """Redis-backed review metadata; Graph checkpoints remain process-local."""

    def __init__(self, redis_client, *, ttl_seconds: int = _REVIEW_TTL_SECONDS) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds

    @staticmethod
    def _key(run_id: str) -> str:
        return f"{_REVIEW_KEY_PREFIX}{run_id}"

    async def save(self, record: ReviewRecord) -> None:
        await self._redis.setex(
            self._key(record.run_id),
            self._ttl_seconds,
            record.model_dump_json(),
        )
        if record.status == RunStatus.WAITING_REVIEW:
            await self._redis.sadd(_PENDING_KEY, record.run_id)
        else:
            await self._redis.srem(_PENDING_KEY, record.run_id)

    async def get(self, run_id: str) -> ReviewRecord | None:
        payload = await self._redis.get(self._key(run_id))
        if payload is None:
            return None
        return ReviewRecord.model_validate_json(payload)

    async def list_pending(self) -> list[ReviewRecord]:
        run_ids = await self._redis.smembers(_PENDING_KEY)
        records: list[ReviewRecord] = []
        stale_ids: list[str] = []
        for raw_run_id in run_ids:
            run_id = raw_run_id.decode() if isinstance(raw_run_id, bytes) else raw_run_id
            record = await self.get(run_id)
            if record is None or record.status != RunStatus.WAITING_REVIEW:
                stale_ids.append(run_id)
                continue
            records.append(record)
        if stale_ids:
            await self._redis.srem(_PENDING_KEY, *stale_ids)
        return sorted(records, key=lambda item: item.created_at)


def build_review_repository(redis_client) -> ReviewRepository:
    if redis_client is None:
        return InMemoryReviewRepository()
    return RedisReviewRepository(redis_client)
