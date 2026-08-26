"""Stable domain models shared by retrieval implementations and the agent."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal, TypeAlias, cast

RetrievalStrategy: TypeAlias = Literal[
    "vector_only",
    "hybrid",
    "hybrid_rerank",
]

RETRIEVAL_STRATEGIES: tuple[RetrievalStrategy, ...] = (
    "vector_only",
    "hybrid",
    "hybrid_rerank",
)

MAX_TOP_K = 100


def validate_strategy(strategy: str) -> RetrievalStrategy:
    """Return a supported retrieval strategy or raise a clear error."""
    if strategy not in RETRIEVAL_STRATEGIES:
        supported = ", ".join(RETRIEVAL_STRATEGIES)
        raise ValueError(
            f"Unsupported retrieval strategy {strategy!r}; expected one of: "
            f"{supported}"
        )
    return cast(RetrievalStrategy, strategy)


def validate_top_k(top_k: int) -> int:
    """Validate the common Top K boundary used by all retrieval stages."""
    if isinstance(top_k, bool) or not isinstance(top_k, int):
        raise TypeError("top_k must be an integer")
    if not 1 <= top_k <= MAX_TOP_K:
        raise ValueError(f"top_k must be between 1 and {MAX_TOP_K}")
    return top_k


def _validate_optional_score(name: str, value: float | None) -> None:
    if value is not None and not math.isfinite(value):
        raise ValueError(f"{name} must be finite when provided")


def _validate_optional_rank(name: str, value: int | None) -> None:
    if value is not None and (
        isinstance(value, bool) or not isinstance(value, int) or value < 1
    ):
        raise ValueError(f"{name} must be a positive integer when provided")


@dataclass(slots=True)
class RetrievedDocument:
    """A citation-ready document enriched by independent retrieval stages.

    Scores are optional because a document may be produced by only one stage.
    Every populated score follows the convention that a larger value is more
    relevant. Raw ranks are one-based.
    """

    document_id: str
    title: str
    content: str
    category: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    source_retrievers: tuple[str, ...] = ()
    vector_score: float | None = None
    vector_rank: int | None = None
    bm25_score: float | None = None
    bm25_rank: int | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None
    final_rank: int | None = None

    def __post_init__(self) -> None:
        if not self.document_id.strip():
            raise ValueError("document_id must not be empty")
        if not self.title.strip():
            raise ValueError("title must not be empty")
        if not self.content.strip():
            raise ValueError("content must not be empty")

        for name in (
            "vector_score",
            "bm25_score",
            "rrf_score",
            "rerank_score",
        ):
            _validate_optional_score(name, getattr(self, name))

        for name in ("vector_rank", "bm25_rank", "final_rank"):
            _validate_optional_rank(name, getattr(self, name))


@dataclass(slots=True)
class RetrievalDiagnostics:
    """Internal retrieval observations that are safe for routing and evals."""

    vector_candidate_count: int = 0
    bm25_candidate_count: int = 0
    fused_candidate_count: int = 0
    returned_count: int = 0
    embedding_latency_ms: float | None = None
    vector_latency_ms: float | None = None
    bm25_latency_ms: float | None = None
    fusion_latency_ms: float | None = None
    rerank_latency_ms: float | None = None
    total_latency_ms: float | None = None
    reranker_fallback: bool = False
    fallback_reason: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "vector_candidate_count",
            "bm25_candidate_count",
            "fused_candidate_count",
            "returned_count",
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise ValueError(f"{name} must be a non-negative integer")

        for name in (
            "embedding_latency_ms",
            "vector_latency_ms",
            "bm25_latency_ms",
            "fusion_latency_ms",
            "rerank_latency_ms",
            "total_latency_ms",
        ):
            value = getattr(self, name)
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError(f"{name} must be finite and non-negative")


@dataclass(slots=True)
class RetrievalResult:
    """Complete result returned through the retrieval service boundary."""

    query: str
    documents: list[RetrievedDocument]
    strategy: RetrievalStrategy
    low_confidence: bool = False
    confidence_reasons: list[str] = field(default_factory=list)
    diagnostics: RetrievalDiagnostics = field(default_factory=RetrievalDiagnostics)

    def __post_init__(self) -> None:
        self.strategy = validate_strategy(self.strategy)
        if self.low_confidence and not self.confidence_reasons:
            raise ValueError(
                "low-confidence results must include at least one reason"
            )
        if self.diagnostics.returned_count != len(self.documents):
            raise ValueError(
                "diagnostics.returned_count must match the document count"
            )
