import pytest

from evals.rerank_replay import _restore_candidates, run_replay


def test_restore_candidates_preserves_scores_and_adds_database_content():
    rows = {"documents": [{
        "document_id": "doc-1",
        "title": "Title",
        "source_retrievers": ["vector", "bm25"],
        "vector_score": 0.43,
        "bm25_score": 2.0,
        "rrf_score": 0.02,
    }]}

    restored = _restore_candidates(rows, {"doc-1": "Authoritative content"})

    assert restored[0].content == "Authoritative content"
    assert restored[0].vector_score == 0.43
    assert restored[0].source_retrievers == ("vector", "bm25")


@pytest.mark.asyncio
async def test_replay_rejects_boolean_concurrency_before_external_access(tmp_path):
    with pytest.raises(ValueError, match="concurrency must be positive"):
        await run_replay(
            tmp_path / "dataset.jsonl",
            tmp_path / "report.json",
            provider_key="dummy",
            base_url="https://example.invalid",
            model="unused",
            database_url="unused",
            concurrency=True,
        )
