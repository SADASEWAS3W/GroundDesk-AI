"""Contract tests for retrieval domain models."""

from __future__ import annotations

import math

import pytest

from agent.retrieval.models import (
    RetrievedDocument,
    RetrievalDiagnostics,
    RetrievalResult,
    validate_strategy,
    validate_top_k,
)


def _document(**overrides) -> RetrievedDocument:
    values = {
        "document_id": "doc-1",
        "title": "Password reset",
        "content": "Open Settings and select Reset Password.",
    }
    values.update(overrides)
    return RetrievedDocument(**values)


def test_document_accepts_independent_stage_scores():
    document = _document(
        source_retrievers=("vector", "bm25"),
        vector_score=0.8,
        vector_rank=1,
        bm25_score=4.2,
        bm25_rank=2,
        rrf_score=0.03,
        rerank_score=0.9,
        final_rank=1,
    )

    assert document.document_id == "doc-1"
    assert document.source_retrievers == ("vector", "bm25")
    assert document.final_rank == 1


@pytest.mark.parametrize("field", ["document_id", "title", "content"])
def test_document_rejects_empty_required_text(field):
    with pytest.raises(ValueError, match=field):
        _document(**{field: "   "})


@pytest.mark.parametrize(
    "field,value",
    [
        ("vector_score", math.nan),
        ("bm25_score", math.inf),
        ("rrf_score", -math.inf),
        ("rerank_score", math.nan),
    ],
)
def test_document_rejects_non_finite_scores(field, value):
    with pytest.raises(ValueError, match=field):
        _document(**{field: value})


@pytest.mark.parametrize("field", ["vector_rank", "bm25_rank", "final_rank"])
@pytest.mark.parametrize("value", [0, 1.5, True])
def test_document_rejects_invalid_ranks(field, value):
    with pytest.raises(ValueError, match=field):
        _document(**{field: value})


def test_result_requires_reason_when_low_confidence():
    with pytest.raises(ValueError, match="at least one reason"):
        RetrievalResult(
            query="question",
            documents=[],
            strategy="vector_only",
            low_confidence=True,
            diagnostics=RetrievalDiagnostics(returned_count=0),
        )


def test_result_checks_diagnostic_document_count():
    with pytest.raises(ValueError, match="returned_count"):
        RetrievalResult(
            query="question",
            documents=[_document()],
            strategy="vector_only",
            diagnostics=RetrievalDiagnostics(returned_count=0),
        )


@pytest.mark.parametrize("value", [-1, 1.5, True])
def test_diagnostics_reject_invalid_candidate_counts(value):
    with pytest.raises(ValueError, match="vector_candidate_count"):
        RetrievalDiagnostics(vector_candidate_count=value)


def test_strategy_validation_lists_supported_values():
    with pytest.raises(ValueError, match="vector_only"):
        validate_strategy("unknown")


@pytest.mark.parametrize("top_k", [0, 101])
def test_top_k_rejects_out_of_range_values(top_k):
    with pytest.raises(ValueError, match="between 1 and 100"):
        validate_top_k(top_k)


def test_top_k_rejects_boolean():
    with pytest.raises(TypeError, match="integer"):
        validate_top_k(True)
