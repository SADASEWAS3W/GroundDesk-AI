from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.retrieval.ingest import embed_chunks, prepare_source


def source_rows(content="Reset your password."):
    return prepare_source(content, source_id="manual/account-v1", title="Account", category="help")


def test_stable_ids_and_revision_changes():
    source, rows = source_rows()
    assert rows == source_rows()[1]
    assert rows[0]["id"] != source_rows("New password steps.")[1][0]["id"]
    assert source["embedding_dimensions"] == 1536
    assert source["source_id"] == "manual/account-v1"


def test_chunk_titles_fit_schema_and_are_unique():
    _, rows = prepare_source("abcd" * 100, source_id="manual", title="长" * 300,
                             category="help", chunk_size=80, overlap=10)
    assert len({row["title"] for row in rows}) == len(rows)
    assert all(len(row["title"]) <= 255 for row in rows)


@pytest.mark.parametrize("content", ["", " \n "])
def test_empty_source_is_rejected(content):
    with pytest.raises(ValueError, match="no non-whitespace"):
        source_rows(content)


async def test_embedding_response_indices_restore_input_order():
    source, rows = prepare_source("x" * 200, source_id="a", title="Title", category="help",
                                  chunk_size=80, overlap=10)
    client = MagicMock()
    client.embeddings.create = AsyncMock(return_value=SimpleNamespace(data=[
        SimpleNamespace(index=i, embedding=[float(i)] * 1536)
        for i in reversed(range(len(rows)))
    ]))
    embedded = await embed_chunks(client, source, rows)
    assert [row["embedding"][0] for row in embedded] == list(range(len(rows)))
    args = client.embeddings.create.call_args.kwargs
    assert args["dimensions"] == 1536
    assert args["input"][0] == "Title\n\n" + rows[0]["content"]
    assert "embedding" not in rows[0]


@pytest.mark.parametrize("data", [
    [], [SimpleNamespace(index=1, embedding=[0.] * 1536)],
    [SimpleNamespace(index=0, embedding=[0.] * 10)],
    [SimpleNamespace(index=0, embedding=[float('nan')] * 1536)],
    [SimpleNamespace(index=0, embedding=[True] * 1536)],
])
async def test_invalid_embeddings_fail_before_persistence(data):
    source, rows = source_rows()
    client = MagicMock()
    client.embeddings.create = AsyncMock(return_value=SimpleNamespace(data=data))
    with pytest.raises(ValueError):
        await embed_chunks(client, source, rows)


async def test_provider_failure_propagates_without_partial_result():
    source, rows = source_rows()
    client = MagicMock()
    client.embeddings.create = AsyncMock(side_effect=RuntimeError("provider unavailable"))
    with pytest.raises(RuntimeError, match="provider unavailable"):
        await embed_chunks(client, source, rows)


async def test_batches_are_limited_to_ten():
    source, rows = prepare_source("x" * 1200, source_id="a", title="T", category="help",
                                  chunk_size=80, overlap=10)
    async def respond(**kwargs):
        return SimpleNamespace(data=[SimpleNamespace(index=i, embedding=[0.] * 1536)
                                     for i in range(len(kwargs["input"]))])
    client = MagicMock()
    client.embeddings.create = AsyncMock(side_effect=respond)
    result = await embed_chunks(client, source, rows)
    assert len(result) == len(rows)
    assert client.embeddings.create.await_count > 1
    assert all(len(call.kwargs["input"]) <= 10 for call in client.embeddings.create.call_args_list)
