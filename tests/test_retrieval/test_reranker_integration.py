"""Opt-in live integration test for the configured model reranker."""

from __future__ import annotations

import os

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_RERANKER_INTEGRATION") != "1",
    reason="set RUN_RERANKER_INTEGRATION=1 to authorize a live model call",
)


async def test_live_reranker_prefers_password_reset_evidence():
    pytest.importorskip("openai")

    from openai import AsyncOpenAI

    from agent.retrieval import LLMReranker, RetrievedDocument

    required = ("DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        pytest.skip(f"missing integration configuration: {', '.join(missing)}")

    client = AsyncOpenAI(
        api_key=os.environ["DASHSCOPE_API_KEY"],
        base_url=os.environ["DASHSCOPE_BASE_URL"],
    )
    reranker = LLMReranker(
        model_client=client,
        model=os.environ.get("QWEN_RERANK_MODEL", "qwen-plus"),
    )
    documents = [
        RetrievedDocument(
            document_id="billing",
            title="Billing Plans",
            content="Compare subscription tiers and invoice periods.",
        ),
        RetrievedDocument(
            document_id="password-reset",
            title="Password Reset",
            content="Open Settings, choose Security, then Reset Password.",
        ),
    ]

    results = await reranker.rerank(
        "How do I reset my password?",
        documents,
        top_k=2,
    )

    assert results[0].document_id == "password-reset"
    assert all(document.rerank_score is not None for document in results)
