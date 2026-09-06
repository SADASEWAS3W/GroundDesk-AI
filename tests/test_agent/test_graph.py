from agent.graph import (
    build_support_graph,
    resume_support_graph,
    run_support_graph,
    validate_answer_citations,
)
from agent.retrieval import FakeRetrievalService, RetrievedDocument
from agent.nodes import GeneratedAnswer


def _document() -> RetrievedDocument:
    return RetrievedDocument(
        document_id="doc-1",
        title="Password reset",
        content="Open Settings and choose Reset Password.",
        source_retrievers=("vector", "bm25"),
        vector_score=0.8,
        final_rank=1,
    )


async def test_graph_completes_grounded_answer_with_bounded_citation():
    graph = build_support_graph(FakeRetrievalService(default_documents=[_document()]))

    result = await run_support_graph(graph, {
        "run_id": "normal-1",
        "conversation_id": "conversation-1",
        "original_query": "How do I reset my password?",
    })

    assert result["status"] == "completed"
    assert result["grounded"] is True
    assert result["requires_human_review"] is False
    assert result["citations"][0]["document_id"] == "doc-1"
    assert "[1]" in result["answer"]


async def test_high_risk_request_interrupts_and_can_be_approved():
    graph = build_support_graph(FakeRetrievalService(default_documents=[_document()]))

    interrupted = await run_support_graph(graph, {
        "run_id": "review-1",
        "conversation_id": "conversation-1",
        "original_query": "Please delete account permanently",
    })

    assert interrupted["status"] == "waiting_review"
    assert interrupted["requires_human_review"] is True
    assert interrupted["review_reason"] == "high_risk_request"

    resumed = await resume_support_graph(graph, "review-1", {"action": "approve"})

    assert resumed["status"] == "completed"
    assert resumed["review_decision"]["action"] == "approve"


async def test_no_evidence_interrupts_before_customer_delivery():
    graph = build_support_graph(FakeRetrievalService())

    result = await run_support_graph(graph, {
        "run_id": "no-evidence-1",
        "conversation_id": "conversation-1",
        "original_query": "unknown question",
    })

    assert result["status"] == "waiting_review"
    assert result["grounded"] is False
    assert "no_retrieval_results" in result["grounding_issues"]
    assert result["citations"] == []


def test_citation_marker_validation_rejects_unknown_index():
    citations = [{"index": 1, "document_id": "doc-1"}]
    assert validate_answer_citations("Supported [2]", citations) == [
        "invalid_citation_marker",
        "unused_citation_marker",
    ]


def test_citation_marker_validation_rejects_declared_but_unused_source():
    citations = [
        {"index": 1, "document_id": "doc-1"},
        {"index": 2, "document_id": "doc-2"},
    ]
    assert validate_answer_citations("Supported [1]", citations) == [
        "unused_citation_marker"
    ]


async def test_natural_account_deletion_phrase_is_high_risk():
    graph = build_support_graph(FakeRetrievalService(default_documents=[_document()]))
    result = await run_support_graph(graph, {
        "run_id": "natural-delete-phrase",
        "conversation_id": "conversation-1",
        "original_query": "Permanently delete my account",
    })

    assert result["status"] == "waiting_review"
    assert result["review_reason"] == "high_risk_request"


class _FailingRewriter:
    async def rewrite(self, query):
        raise RuntimeError("provider unavailable")


class _UnknownCitationGenerator:
    async def generate(self, query, documents):
        return GeneratedAnswer(
            answer="Unsupported answer [1]",
            citation_document_ids=["unknown-document"],
        )


async def test_rewrite_failure_falls_back_to_original_query():
    graph = build_support_graph(
        FakeRetrievalService(default_documents=[_document()]),
        query_rewriter=_FailingRewriter(),
    )
    result = await run_support_graph(graph, {
        "run_id": "rewrite-fallback",
        "conversation_id": "conversation-1",
        "original_query": "  Reset   my password  ",
    })

    assert result["status"] == "completed"
    assert result["rewritten_query"] == "Reset my password"
    assert result["rewrite_fallback"] is True


async def test_unknown_generated_citation_enters_review():
    graph = build_support_graph(
        FakeRetrievalService(default_documents=[_document()]),
        answer_generator=_UnknownCitationGenerator(),
    )
    result = await run_support_graph(graph, {
        "run_id": "invalid-citation",
        "conversation_id": "conversation-1",
        "original_query": "Reset my password",
    })

    assert result["status"] == "waiting_review"
    assert "invalid_reported_citation_source" in result["grounding_issues"]
