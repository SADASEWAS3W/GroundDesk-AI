"""Tests for the in-process BM25 retriever."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.retrieval import (
    BM25IndexNotBuiltError,
    InMemoryBM25Retriever,
    RetrievedDocument,
    load_knowledge_documents,
)


class _AsyncContextManager:
    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, *args):
        return False


def _document(number: int, title: str, content: str) -> RetrievedDocument:
    return RetrievedDocument(
        document_id=f"doc-{number}",
        title=title,
        content=content,
        category="support",
    )


def _corpus() -> list[RetrievedDocument]:
    return [
        _document(1, "Password Reset", "Reset your password in account settings."),
        _document(2, "API Documentation", "API rate limits and authentication."),
        _document(3, "Data Export", "Export all account data as a ZIP file."),
    ]


async def test_search_requires_an_explicit_build():
    retriever = InMemoryBM25Retriever()

    with pytest.raises(BM25IndexNotBuiltError):
        await retriever.search("password", top_k=3)


async def test_exact_keywords_rank_the_matching_document_first():
    retriever = InMemoryBM25Retriever()
    status = retriever.build(_corpus())

    documents = await retriever.search("password reset", top_k=3)

    assert status.built is True
    assert status.document_count == 3
    assert [document.document_id for document in documents] == ["doc-1"]
    assert documents[0].bm25_rank == 1
    assert documents[0].bm25_score is not None
    assert documents[0].source_retrievers == ("bm25",)


async def test_non_matching_query_does_not_return_zero_score_documents():
    retriever = InMemoryBM25Retriever()
    retriever.build(_corpus())

    assert await retriever.search("quantum computing", top_k=3) == []


async def test_empty_corpus_and_empty_query_are_normal_empty_results():
    retriever = InMemoryBM25Retriever()
    retriever.build([])
    assert await retriever.search("password", top_k=3) == []

    retriever.rebuild(_corpus())
    assert await retriever.search("   ", top_k=3) == []


async def test_corpus_with_no_searchable_tokens_is_safe():
    retriever = InMemoryBM25Retriever()
    retriever.build([_document(1, "...", "!!!")])

    assert await retriever.search("password", top_k=3) == []


async def test_rebuild_atomically_replaces_the_searchable_snapshot():
    retriever = InMemoryBM25Retriever()
    retriever.build(_corpus())
    retriever.rebuild([_document(4, "Webhook Error", "Resolve webhook E401 failures.")])

    assert await retriever.search("password", top_k=3) == []
    result = await retriever.search("E401", top_k=3)
    assert [document.document_id for document in result] == ["doc-4"]
    assert retriever.status.document_count == 1


def test_build_rejects_duplicate_document_ids():
    retriever = InMemoryBM25Retriever()
    duplicate = _document(1, "Another title", "Another body")

    with pytest.raises(ValueError, match="unique document_id"):
        retriever.build([_corpus()[0], duplicate])


async def test_returned_documents_do_not_mutate_the_index_snapshot():
    retriever = InMemoryBM25Retriever()
    retriever.build(_corpus())
    first = await retriever.search("password", top_k=3)
    first[0].metadata["changed"] = True

    second = await retriever.search("password", top_k=3)
    assert "changed" not in second[0].metadata


async def test_load_knowledge_documents_maps_stable_database_fields():
    connection = AsyncMock()
    document_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
    connection.fetch.return_value = [
        {
            "id": document_id,
            "title": "Password Reset",
            "content": "Reset instructions.",
            "category": "account",
        }
    ]
    pool = MagicMock()
    pool.acquire.return_value = _AsyncContextManager(connection)

    documents = await load_knowledge_documents(pool)

    assert documents[0].document_id == str(document_id)
    assert documents[0].metadata == {"source": "knowledge_base"}
    connection.fetch.assert_awaited_once()
