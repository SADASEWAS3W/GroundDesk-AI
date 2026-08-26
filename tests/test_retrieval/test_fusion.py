"""Tests for Reciprocal Rank Fusion."""

from __future__ import annotations

import pytest

from agent.retrieval import ReciprocalRankFusion, RetrievedDocument


def _document(
    document_id: str,
    *,
    vector_rank: int | None = None,
    bm25_rank: int | None = None,
) -> RetrievedDocument:
    return RetrievedDocument(
        document_id=document_id,
        title=f"Title {document_id}",
        content=f"Content {document_id}",
        vector_score=0.0 if vector_rank is not None else None,
        vector_rank=vector_rank,
        bm25_score=0.0 if bm25_rank is not None else None,
        bm25_rank=bm25_rank,
    )


def test_document_found_by_both_retrievers_ranks_first_and_is_merged():
    fusion = ReciprocalRankFusion(rank_constant=60)
    vector = [_document("shared", vector_rank=1), _document("vector", vector_rank=2)]
    bm25 = [_document("keyword", bm25_rank=1), _document("shared", bm25_rank=2)]

    results = fusion.fuse(vector, bm25, top_k=3)

    assert [document.document_id for document in results] == [
        "shared",
        "keyword",
        "vector",
    ]
    shared = results[0]
    assert shared.vector_rank == 1
    assert shared.bm25_rank == 2
    assert shared.vector_score == 0.0
    assert shared.bm25_score == 0.0
    assert shared.source_retrievers == ("vector", "bm25")
    assert shared.rrf_score == pytest.approx(1 / 61 + 1 / 62)
    assert [document.final_rank for document in results] == [1, 2, 3]


def test_single_retriever_documents_remain_eligible():
    results = ReciprocalRankFusion().fuse(
        [_document("vector-only", vector_rank=1)],
        [],
        top_k=3,
    )

    assert [document.document_id for document in results] == ["vector-only"]
    assert results[0].rrf_score == pytest.approx(1 / 61)


def test_equal_scores_have_stable_document_id_tiebreaker():
    results = ReciprocalRankFusion().fuse(
        [_document("b", vector_rank=1)],
        [_document("a", bm25_rank=1)],
        top_k=2,
    )

    assert [document.document_id for document in results] == ["a", "b"]


def test_duplicate_id_within_one_retriever_is_rejected():
    duplicate = _document("duplicate", vector_rank=1)

    with pytest.raises(ValueError, match="duplicate document_id"):
        ReciprocalRankFusion().fuse([duplicate, duplicate], [], top_k=3)


def test_inconsistent_content_for_shared_id_is_rejected():
    vector = _document("shared", vector_rank=1)
    keyword = RetrievedDocument(
        document_id="shared",
        title="Different title",
        content="Different content",
        bm25_score=1.0,
        bm25_rank=1,
    )

    with pytest.raises(ValueError, match="inconsistent document content"):
        ReciprocalRankFusion().fuse([vector], [keyword], top_k=3)


@pytest.mark.parametrize("rank_constant", [0, -1, True, 1.5])
def test_invalid_rank_constant_is_rejected(rank_constant):
    with pytest.raises(ValueError, match="positive integer"):
        ReciprocalRankFusion(rank_constant=rank_constant)
