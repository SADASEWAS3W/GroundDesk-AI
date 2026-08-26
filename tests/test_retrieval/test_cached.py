from unittest.mock import AsyncMock

from agent.retrieval import (
    CachedRetrievalService,
    RetrievalDiagnostics,
    RetrievalResult,
    RetrievedDocument,
)


async def test_second_retrieval_uses_cache_without_calling_service(mock_redis):
    document = RetrievedDocument(
        document_id="doc-1",
        title="Title",
        content="Content",
        source_retrievers=("vector",),
        vector_score=0.8,
        final_rank=1,
    )
    inner = AsyncMock()
    inner.retrieve.return_value = RetrievalResult(
        query="query",
        documents=[document],
        strategy="hybrid",
        diagnostics=RetrievalDiagnostics(returned_count=1),
    )
    cached = CachedRetrievalService(inner, mock_redis)

    first = await cached.retrieve(" Query ", strategy="hybrid", top_k=3)
    second = await cached.retrieve("query", strategy="hybrid", top_k=3)

    assert first.documents[0].document_id == "doc-1"
    assert second.documents[0].source_retrievers == ("vector",)
    assert second.diagnostics.attributes["cache_hit"] is True
    inner.retrieve.assert_awaited_once()
