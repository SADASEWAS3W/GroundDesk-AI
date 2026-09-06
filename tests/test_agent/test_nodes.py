import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.nodes import (
    GeneratedAnswer,
    GenerationProviderError,
    LLMAnswerGenerator,
    LLMQueryRewriter,
    RewriteProviderError,
)


def _client_with_content(content: str):
    client = MagicMock()
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )
    client.chat.completions.create = AsyncMock(return_value=response)
    return client


async def test_llm_query_rewriter_returns_one_normalized_query():
    client = _client_with_content("  reset   account password  ")
    rewriter = LLMQueryRewriter(client)

    assert await rewriter.rewrite("I cannot sign in") == "reset account password"
    client.chat.completions.create.assert_awaited_once()


async def test_llm_query_rewriter_wraps_empty_provider_output():
    rewriter = LLMQueryRewriter(_client_with_content(""))
    with pytest.raises(RewriteProviderError):
        await rewriter.rewrite("I cannot sign in")


async def test_llm_answer_generator_parses_structured_result():
    client = _client_with_content(json.dumps({
        "answer": "Open settings and reset the password [1].",
        "citation_document_ids": ["doc-1"],
    }))
    generator = LLMAnswerGenerator(client)

    result = await generator.generate("Reset password", [{
        "document_id": "doc-1",
        "title": "Password reset",
        "content": "Open settings.",
    }])

    assert result == GeneratedAnswer(
        answer="Open settings and reset the password [1].",
        citation_document_ids=["doc-1"],
    )
    assert client.chat.completions.create.await_args.kwargs["max_tokens"] == 800


def test_llm_answer_generator_rejects_invalid_bounds():
    client = _client_with_content("{}")
    with pytest.raises(ValueError, match="max_document_chars"):
        LLMAnswerGenerator(client, max_document_chars=0)
    with pytest.raises(ValueError, match="max_output_tokens"):
        LLMAnswerGenerator(client, max_output_tokens=0)


async def test_llm_answer_generator_rejects_invalid_payload():
    generator = LLMAnswerGenerator(_client_with_content("not-json"))
    with pytest.raises(GenerationProviderError):
        await generator.generate("Reset password", [{
            "document_id": "doc-1",
            "title": "Password reset",
            "content": "Open settings.",
        }])
