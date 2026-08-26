"""Shared state contract for the customer-support LangGraph workflow."""

from __future__ import annotations

from typing import Any, TypedDict


class SupportState(TypedDict, total=False):
    run_id: str
    conversation_id: str
    original_query: str
    rewritten_query: str
    retrieved_documents: list[dict[str, Any]]
    answer: str
    citations: list[dict[str, Any]]
    grounded: bool
    grounding_issues: list[str]
    low_confidence: bool
    confidence_reasons: list[str]
    requires_human_review: bool
    review_reason: str | None
    review_decision: dict[str, Any]
    status: str
