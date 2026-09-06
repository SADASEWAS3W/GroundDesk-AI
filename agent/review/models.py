"""Stable domain models for human-review state."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class RunStatus(StrEnum):
    PROCESSING = "processing"
    WAITING_REVIEW = "waiting_review"
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"


class ReviewAction(StrEnum):
    APPROVE = "approve"
    EDIT = "edit"
    REJECT = "reject"


class ReviewRecord(BaseModel):
    """Internal review record; draft fields are never customer-facing."""

    run_id: str = Field(min_length=1)
    status: RunStatus = RunStatus.WAITING_REVIEW
    original_query: str
    draft_answer: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    retrieved_document_ids: list[str] = Field(default_factory=list)
    review_reason: str | None = None
    customer_id: str | None = None
    conversation_id: str | None = None
    ticket_id: str | None = None
    channel: str = "web"
    final_answer: str | None = None
    decision_action: ReviewAction | None = None
    decision_answer: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def with_decision(
        self,
        *,
        action: ReviewAction,
        status: RunStatus,
        final_answer: str | None,
        decision_answer: str | None,
    ) -> "ReviewRecord":
        return self.model_copy(update={
            "status": status,
            "final_answer": final_answer,
            "decision_action": action,
            "decision_answer": decision_answer,
            "updated_at": datetime.now(UTC),
        })
