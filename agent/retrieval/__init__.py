"""Provider-neutral retrieval contracts and services."""

from agent.retrieval.models import (
    MAX_TOP_K,
    RETRIEVAL_STRATEGIES,
    RetrievedDocument,
    RetrievalDiagnostics,
    RetrievalResult,
    RetrievalStrategy,
    validate_strategy,
    validate_top_k,
)
from agent.retrieval.protocols import (
    BM25Retriever,
    FusionStrategy,
    Reranker,
    RetrievalService,
    VectorRetriever,
)
from agent.retrieval.service import FakeRetrievalService

__all__ = [
    "BM25Retriever",
    "FakeRetrievalService",
    "FusionStrategy",
    "MAX_TOP_K",
    "RETRIEVAL_STRATEGIES",
    "Reranker",
    "RetrievedDocument",
    "RetrievalDiagnostics",
    "RetrievalResult",
    "RetrievalService",
    "RetrievalStrategy",
    "VectorRetriever",
    "validate_strategy",
    "validate_top_k",
]
