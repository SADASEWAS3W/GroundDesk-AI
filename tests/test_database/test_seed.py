"""Tests for database.migrations.002_seed_knowledge_base — article data."""

import importlib
from unittest.mock import AsyncMock, MagicMock

import pytest

_mod = importlib.import_module("database.migrations.002_seed_knowledge_base")
ARTICLES = _mod.ARTICLES


def test_seed_has_minimum_articles():
    """KB must have at least 15 articles (spec SC-010)."""
    assert len(ARTICLES) >= 15


def test_seed_articles_have_required_fields():
    """Each article has title, content, and category."""
    for article in ARTICLES:
        assert "title" in article
        assert "content" in article
        assert "category" in article
        assert len(article["title"]) > 0
        assert len(article["content"]) > 0


def test_seed_articles_cover_multiple_categories():
    """Articles span at least 5 distinct categories."""
    categories = {a["category"] for a in ARTICLES}
    assert len(categories) >= 5


async def test_generate_embeddings_requests_1536_dimensions():
    client = MagicMock()
    item = MagicMock()
    item.embedding = [0.01] * 1536
    response = MagicMock(data=[item])
    client.embeddings.create = AsyncMock(return_value=response)

    embeddings = await _mod._generate_embeddings(
        client, ["example"], "text-embedding-v4", 1536
    )

    assert len(embeddings[0]) == 1536
    client.embeddings.create.assert_awaited_once_with(
        input=["example"],
        model="text-embedding-v4",
        dimensions=1536,
        encoding_format="float",
    )


async def test_generate_embeddings_rejects_wrong_dimensions():
    client = MagicMock()
    item = MagicMock()
    item.embedding = [0.01] * 1024
    client.embeddings.create = AsyncMock(return_value=MagicMock(data=[item]))

    with pytest.raises(ValueError, match="1536"):
        await _mod._generate_embeddings(
            client, ["example"], "text-embedding-v4", 1536
        )


async def test_generate_embeddings_batches_at_ten_items():
    client = MagicMock()

    def response_for(**kwargs):
        return MagicMock(
            data=[MagicMock(embedding=[0.01] * 1536) for _ in kwargs["input"]]
        )

    client.embeddings.create = AsyncMock(side_effect=response_for)
    embeddings = await _mod._generate_embeddings(
        client, [f"article-{index}" for index in range(21)]
    )

    assert len(embeddings) == 21
    assert [len(call.kwargs["input"]) for call in client.embeddings.create.await_args_list] == [
        10,
        10,
        1,
    ]
