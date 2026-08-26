"""Eval-calibrated, provider-neutral retrieval confidence signals."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from agent.retrieval.models import RetrievedDocument, RetrievalDiagnostics


DEFAULT_MIN_TOP1_VECTOR_SCORE = 0.40


@dataclass(frozen=True, slots=True)
class RetrievalConfidencePolicy:
    """Classify retrieval output using thresholds established by eval data."""

    min_top1_vector_score: float | None = DEFAULT_MIN_TOP1_VECTOR_SCORE
    mark_reranker_fallback: bool = True

    def __post_init__(self) -> None:
        threshold = self.min_top1_vector_score
        if threshold is not None and (
            isinstance(threshold, bool)
            or not isinstance(threshold, (int, float))
            or not math.isfinite(threshold)
            or not -1.0 <= threshold <= 1.0
        ):
            raise ValueError("min_top1_vector_score must be between -1 and 1")

    def reasons(
        self,
        documents: Sequence[RetrievedDocument],
        diagnostics: RetrievalDiagnostics,
    ) -> list[str]:
        if not documents:
            return ["no_retrieval_results"]

        reasons: list[str] = []
        top1_vector_score = documents[0].vector_score
        if (
            self.min_top1_vector_score is not None
            and top1_vector_score is not None
            and top1_vector_score < self.min_top1_vector_score
        ):
            reasons.append("top1_vector_score_below_threshold")
        if self.mark_reranker_fallback and diagnostics.reranker_fallback:
            reasons.append("reranker_fallback")
        return reasons
