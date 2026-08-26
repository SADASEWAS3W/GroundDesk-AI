"""Reciprocal Rank Fusion for vector and BM25 candidates."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import replace

from agent.retrieval.models import RetrievedDocument, validate_top_k


class ReciprocalRankFusion:
    """Fuse rankings without comparing vector and BM25 raw score scales."""

    def __init__(self, *, rank_constant: int = 60) -> None:
        if (
            isinstance(rank_constant, bool)
            or not isinstance(rank_constant, int)
            or rank_constant < 1
        ):
            raise ValueError("rank_constant must be a positive integer")
        self._rank_constant = rank_constant

    def fuse(
        self,
        vector_documents: Sequence[RetrievedDocument],
        bm25_documents: Sequence[RetrievedDocument],
        *,
        top_k: int,
    ) -> list[RetrievedDocument]:
        checked_top_k = validate_top_k(top_k)
        documents: dict[str, RetrievedDocument] = {}
        scores: dict[str, float] = {}
        best_input_rank: dict[str, int] = {}

        self._accumulate(
            documents,
            scores,
            best_input_rank,
            vector_documents,
            retriever="vector",
        )
        self._accumulate(
            documents,
            scores,
            best_input_rank,
            bm25_documents,
            retriever="bm25",
        )

        ranked_ids = sorted(
            documents,
            key=lambda document_id: (
                -scores[document_id],
                best_input_rank[document_id],
                document_id,
            ),
        )
        return [
            replace(
                documents[document_id],
                metadata=dict(documents[document_id].metadata),
                rrf_score=scores[document_id],
                final_rank=rank,
            )
            for rank, document_id in enumerate(ranked_ids[:checked_top_k], start=1)
        ]

    def _accumulate(
        self,
        documents: dict[str, RetrievedDocument],
        scores: dict[str, float],
        best_input_rank: dict[str, int],
        ranked_documents: Sequence[RetrievedDocument],
        *,
        retriever: str,
    ) -> None:
        seen: set[str] = set()
        for rank, incoming in enumerate(ranked_documents, start=1):
            if incoming.document_id in seen:
                raise ValueError(
                    f"duplicate document_id in {retriever} results: "
                    f"{incoming.document_id}"
                )
            seen.add(incoming.document_id)
            scores[incoming.document_id] = scores.get(incoming.document_id, 0.0) + (
                1.0 / (self._rank_constant + rank)
            )
            best_input_rank[incoming.document_id] = min(
                best_input_rank.get(incoming.document_id, math.inf),
                rank,
            )
            documents[incoming.document_id] = self._merge(
                documents.get(incoming.document_id),
                incoming,
                retriever=retriever,
                rank=rank,
            )

    @staticmethod
    def _merge(
        existing: RetrievedDocument | None,
        incoming: RetrievedDocument,
        *,
        retriever: str,
        rank: int,
    ) -> RetrievedDocument:
        if existing is None:
            sources = tuple(dict.fromkeys((*incoming.source_retrievers, retriever)))
            return replace(
                incoming,
                metadata=dict(incoming.metadata),
                source_retrievers=sources,
                vector_rank=incoming.vector_rank or (rank if retriever == "vector" else None),
                bm25_rank=incoming.bm25_rank or (rank if retriever == "bm25" else None),
            )

        if existing.title != incoming.title or existing.content != incoming.content:
            raise ValueError(
                "inconsistent document content for shared document_id: "
                f"{incoming.document_id}"
            )

        sources = tuple(
            dict.fromkeys((*existing.source_retrievers, *incoming.source_retrievers, retriever))
        )
        metadata = {**incoming.metadata, **existing.metadata}
        return replace(
            existing,
            metadata=metadata,
            source_retrievers=sources,
            vector_score=(
                existing.vector_score
                if existing.vector_score is not None
                else incoming.vector_score
            ),
            vector_rank=(
                existing.vector_rank
                if existing.vector_rank is not None
                else incoming.vector_rank
            ),
            bm25_score=(
                existing.bm25_score
                if existing.bm25_score is not None
                else incoming.bm25_score
            ),
            bm25_rank=(
                existing.bm25_rank
                if existing.bm25_rank is not None
                else incoming.bm25_rank
            ),
        )
