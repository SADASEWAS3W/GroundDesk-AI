"""Deterministic retrieval metrics."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetrievalMetricSummary:
    evaluated_queries: int
    answerable_queries: int
    no_answer_queries: int
    recall_at_k: float
    mrr: float
    no_answer_accuracy: float


def recall_at_k(relevant: set[str], predicted: Sequence[str], *, k: int) -> float:
    if k < 1:
        raise ValueError("k must be positive")
    if not relevant:
        raise ValueError("recall is undefined without relevant documents")
    return len(relevant.intersection(predicted[:k])) / len(relevant)


def reciprocal_rank(relevant: set[str], predicted: Sequence[str]) -> float:
    if not relevant:
        raise ValueError("reciprocal rank is undefined without relevant documents")
    for rank, document_id in enumerate(predicted, start=1):
        if document_id in relevant:
            return 1.0 / rank
    return 0.0


def percentile(values: Sequence[float], percentile_value: float) -> float:
    if not values:
        return 0.0
    if not 0 <= percentile_value <= 100:
        raise ValueError("percentile must be between 0 and 100")
    ordered = sorted(values)
    index = math.ceil((percentile_value / 100) * len(ordered)) - 1
    return float(ordered[max(0, index)])


def summarize_predictions(
    cases: Sequence[tuple[set[str], Sequence[str]]], *, k: int = 3
) -> RetrievalMetricSummary:
    answerable = [(relevant, predicted) for relevant, predicted in cases if relevant]
    no_answer = [(relevant, predicted) for relevant, predicted in cases if not relevant]
    recall = (
        sum(recall_at_k(relevant, predicted, k=k) for relevant, predicted in answerable)
        / len(answerable)
        if answerable
        else 0.0
    )
    mrr = (
        sum(reciprocal_rank(relevant, predicted) for relevant, predicted in answerable)
        / len(answerable)
        if answerable
        else 0.0
    )
    no_answer_accuracy = (
        sum(not predicted for _, predicted in no_answer) / len(no_answer)
        if no_answer
        else 0.0
    )
    return RetrievalMetricSummary(
        evaluated_queries=len(cases),
        answerable_queries=len(answerable),
        no_answer_queries=len(no_answer),
        recall_at_k=recall,
        mrr=mrr,
        no_answer_accuracy=no_answer_accuracy,
    )
