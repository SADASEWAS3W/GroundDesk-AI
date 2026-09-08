"""Tests for Redis-backed API request guards."""

from __future__ import annotations

import api.request_guard as guard


async def test_idempotency_claim_returns_the_original_job(mock_redis):
    claimed, existing = await guard.claim_idempotent_job(
        mock_redis,
        "submission-1",
        "job-1",
    )
    duplicate_claimed, duplicate_job = await guard.claim_idempotent_job(
        mock_redis,
        "submission-1",
        "job-2",
    )

    assert claimed is True
    assert existing is None
    assert duplicate_claimed is False
    assert duplicate_job == "job-1"
    assert await guard.get_idempotent_job(mock_redis, "submission-1") == "job-1"

    await guard.release_idempotent_job(mock_redis, "submission-1", "job-1")
    assert await guard.get_idempotent_job(mock_redis, "submission-1") is None


async def test_rate_limit_returns_a_retry_window(monkeypatch, mock_redis):
    monkeypatch.setattr(guard, "CHAT_RATE_LIMIT_REQUESTS", 2)
    monkeypatch.setattr(guard, "CHAT_RATE_LIMIT_WINDOW_SECONDS", 30)

    assert (await guard.check_chat_rate_limit(mock_redis, "customer")).allowed
    assert (await guard.check_chat_rate_limit(mock_redis, "customer")).allowed
    rejected = await guard.check_chat_rate_limit(mock_redis, "customer")

    assert rejected.allowed is False
    assert 1 <= rejected.retry_after <= 30


async def test_review_lock_rejects_a_parallel_owner(mock_redis):
    acquired, owner_id = await guard.acquire_review_lock(mock_redis, "review-1")
    duplicate_acquired, duplicate_owner = await guard.acquire_review_lock(
        mock_redis,
        "review-1",
    )

    assert acquired is True
    assert owner_id
    assert duplicate_acquired is False
    assert duplicate_owner is None

    await guard.release_review_lock(mock_redis, "review-1", owner_id)
    reacquired, _ = await guard.acquire_review_lock(mock_redis, "review-1")
    assert reacquired is True


async def test_guards_fail_open_without_redis():
    assert await guard.get_idempotent_job(None, "key") is None
    assert (await guard.check_chat_rate_limit(None, "customer")).allowed
    assert await guard.acquire_review_lock(None, "review-1") == (True, None)
