from types import SimpleNamespace

from agent.application import (
    SupportApplicationService,
    SupportBusinessContext,
    SupportRequest,
)
from agent.graph import build_support_graph
from agent.retrieval import FakeRetrievalService, RetrievedDocument
from agent.review import InMemoryReviewRepository


def _document() -> RetrievedDocument:
    return RetrievedDocument(
        document_id="doc-1",
        title="Password reset",
        content="Open Settings and choose Reset Password.",
        source_retrievers=("vector", "bm25"),
        vector_score=0.8,
        final_rank=1,
    )


def test_support_request_rejects_an_unknown_channel():
    import pytest

    with pytest.raises(ValueError, match="channel"):
        SupportRequest(
            run_id="run-1",
            message="Question",
            identifier_value="alice@example.com",
            channel="carrier-pigeon",
        )


class FakePersistence:
    def __init__(self) -> None:
        self.business = SupportBusinessContext(
            customer_id="customer-1",
            ticket_id="ticket-1",
            conversation_id="conversation-1",
            channel="web",
        )
        self.calls: list[tuple] = []

    async def prepare(self, request):
        self.calls.append(("prepare", request))
        return self.business

    async def complete(self, business, answer, *, response_time_ms):
        self.calls.append(("complete", business, answer, response_time_ms))

    async def escalate(self, business, reason, *, response_time_ms):
        self.calls.append(("escalate", business, reason, response_time_ms))

    async def deliver_reviewed(self, business, answer):
        self.calls.append(("deliver_reviewed", business, answer))

    async def fail(self, business, reason, *, response_time_ms):
        self.calls.append(("fail", business, reason, response_time_ms))


async def test_application_service_completes_with_real_business_ids():
    persistence = FakePersistence()
    context = SimpleNamespace(
        support_graph=build_support_graph(
            FakeRetrievalService(default_documents=[_document()])
        ),
        review_repository=InMemoryReviewRepository(),
    )
    service = SupportApplicationService(context, persistence=persistence)

    result = await service.run(SupportRequest(
        run_id="run-1",
        message="How do I reset my password?",
        identifier_value="alice@example.com",
        channel="web",
        name="Alice",
    ))

    assert result["status"] == "completed"
    assert result["conversation_id"] == "conversation-1"
    assert result["ticket_id"] == "ticket-1"
    assert [call[0] for call in persistence.calls] == ["prepare", "complete"]


async def test_application_service_escalates_without_delivering_draft():
    persistence = FakePersistence()
    context = SimpleNamespace(
        support_graph=build_support_graph(
            FakeRetrievalService(default_documents=[_document()])
        ),
        review_repository=InMemoryReviewRepository(),
    )
    service = SupportApplicationService(context, persistence=persistence)

    result = await service.run(SupportRequest(
        run_id="run-review",
        message="Please delete account permanently",
        identifier_value="alice@example.com",
        channel="web",
    ))

    assert result["status"] == "waiting_review"
    assert result["response"] is None
    assert [call[0] for call in persistence.calls] == ["prepare", "escalate"]
    record = await context.review_repository.get("run-review")
    assert record is not None
    assert record.conversation_id == "conversation-1"
    assert record.draft_answer


async def test_application_service_delivers_human_review_once_when_called():
    persistence = FakePersistence()
    context = SimpleNamespace(
        support_graph=None,
        review_repository=InMemoryReviewRepository(),
    )
    service = SupportApplicationService(context, persistence=persistence)
    record = await context.review_repository.get("missing")
    assert record is None

    from agent.review import ReviewRecord

    saved = ReviewRecord(
        run_id="run-review",
        original_query="Refund",
        draft_answer="Draft",
        customer_id="customer-1",
        ticket_id="ticket-1",
        conversation_id="conversation-1",
        channel="web",
    )
    await service.deliver_reviewed(saved, "Human approved answer")

    assert persistence.calls == [(
        "deliver_reviewed",
        persistence.business,
        "Human approved answer",
    )]


class FailingGraph:
    async def ainvoke(self, state, config):
        raise RuntimeError("generation failed")


async def test_application_service_marks_business_failure_before_reraising():
    persistence = FakePersistence()
    context = SimpleNamespace(
        support_graph=FailingGraph(),
        review_repository=InMemoryReviewRepository(),
    )
    service = SupportApplicationService(context, persistence=persistence)

    import pytest

    with pytest.raises(RuntimeError, match="generation failed"):
        await service.run(SupportRequest(
            run_id="run-failed",
            message="Question",
            identifier_value="alice@example.com",
            channel="web",
        ))

    assert [call[0] for call in persistence.calls] == ["prepare", "fail"]
