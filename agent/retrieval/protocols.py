"""Structural interfaces for independently replaceable retrieval stages."""

from __future__ import annotations

from typing import Protocol, Sequence

from agent.retrieval.models import (
    RetrievedDocument,
    RetrievalResult,
    RetrievalStrategy,
)


class VectorRetriever(Protocol):
    """Retrieve semantically similar documents from a vector store."""

    async def search(self, query: str, *, top_k: int) -> list[RetrievedDocument]:
        """Return one-based ranked documents with vector scores."""
        ...


class BM25Retriever(Protocol):
    """Retrieve documents from an in-process BM25 index."""

    async def search(self, query: str, *, top_k: int) -> list[RetrievedDocument]:
        """Return one-based ranked documents with BM25 scores."""
        ...


class FusionStrategy(Protocol):
    """Merge independent result lists without assuming comparable scores."""

    def fuse(
        self,
        vector_documents: Sequence[RetrievedDocument],
        bm25_documents: Sequence[RetrievedDocument],
        *,
        top_k: int,
    ) -> list[RetrievedDocument]:
        """Return fused candidates with stable IDs and ranks."""
        ...


class Reranker(Protocol):
    """Reorder only the supplied candidate documents for a query."""

    async def rerank(
        self,
        query: str,
        documents: Sequence[RetrievedDocument],
        *,
        top_k: int,
    ) -> list[RetrievedDocument]:
        """Return at most Top K documents from the supplied candidate set."""
        ...


class RetrievalService(Protocol):
    """Single retrieval boundary consumed by orchestration code."""

    async def retrieve(
        self,
        query: str,
        *,
        strategy: RetrievalStrategy = "hybrid_rerank",
        top_k: int = 3,
    ) -> RetrievalResult:
        """Retrieve citation-ready evidence for a normalized query."""
        ...
