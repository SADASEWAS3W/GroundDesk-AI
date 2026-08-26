from agent.graph import build_support_graph, resume_support_graph, run_support_graph
from agent.retrieval import FakeRetrievalService, RetrievedDocument


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
