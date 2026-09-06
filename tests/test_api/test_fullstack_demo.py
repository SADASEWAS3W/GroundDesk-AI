"""Offline acceptance tests for the two interview-demo business flows."""

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from agent.application import (
    SupportApplicationService,
    SupportBusinessContext,
)
from agent.graph import build_support_graph
from agent.retrieval import FakeRetrievalService, RetrievedDocument
from agent.review import InMemoryReviewRepository
from api.main import app


class _DemoPersistence:
    def __init__(self) -> None:
        self.business = SupportBusinessContext(
            customer_id="customer-demo",
            ticket_id="ticket-demo",
            conversation_id="conversation-demo",
            channel="web",
        )
        self.calls: list[str] = []

    async def prepare(self, request):
        self.calls.append("prepare")
        return self.business

    async def complete(self, business, answer, *, response_time_ms):
        self.calls.append("complete")

    async def escalate(self, business, reason, *, response_time_ms):
        self.calls.append("escalate")

    async def deliver_reviewed(self, business, answer):
        self.calls.append("deliver_reviewed")

    async def fail(self, business, reason, *, response_time_ms):
        self.calls.append("fail")


@pytest.fixture()
async def demo_client():
    document = RetrievedDocument(
        document_id="doc-demo",
        title="Password and account policy",
        content="Open Settings and follow the verified account instructions.",
        source_retrievers=("vector", "bm25"),
        vector_score=0.85,
        final_rank=1,
    )
    persistence = _DemoPersistence()
    context = SimpleNamespace(
        db_pool=None,
        redis_client=None,
        support_graph=build_support_graph(
            FakeRetrievalService(default_documents=[document])
        ),
        review_repository=InMemoryReviewRepository(),
        support_service=None,
    )
    context.support_service = SupportApplicationService(
        context,
        persistence=persistence,
    )
    app.state.agent_ctx = context
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, persistence


async def test_demo_one_grounded_answer_reaches_customer_with_real_business_ids(
    demo_client,
):
    client, persistence = demo_client

    response = await client.post("/api/chat?sync=true", json={
        "message": "How do I reset my password?",
        "email": "demo@example.com",
        "channel": "web",
    })

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["response"].endswith("[1]")
    assert payload["citations"][0]["document_id"] == "doc-demo"
    assert payload["ticket_id"] == "ticket-demo"
    assert payload["conversation_id"] == "conversation-demo"
    assert persistence.calls == ["prepare", "complete"]


async def test_demo_two_draft_is_hidden_then_approved_and_delivered_once(demo_client):
    client, persistence = demo_client

    submitted = await client.post("/api/chat?sync=true", json={
        "message": "Please refund my latest invoice",
        "email": "demo@example.com",
        "channel": "web",
    })
    submitted_payload = submitted.json()
    run_id = submitted_payload["run_id"]

    assert submitted.status_code == 200
    assert submitted_payload["status"] == "waiting_review"
    assert submitted_payload["response"] is None
    assert persistence.calls == ["prepare", "escalate"]

    customer_poll = await client.get(f"/api/jobs/{run_id}")
    assert customer_poll.status_code == 200
    assert customer_poll.json()["status"] == "waiting_review"
    assert customer_poll.json()["response"] is None

    detail = await client.get(f"/api/reviews/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["draft_answer"].endswith("[1]")

    approved = await client.post(
        f"/api/reviews/{run_id}", json={"action": "approve"}
    )
    repeated = await client.post(
        f"/api/reviews/{run_id}", json={"action": "approve"}
    )

    assert approved.status_code == 200
    assert approved.json()["status"] == "completed"
    assert approved.json()["response"].endswith("[1]")
    assert repeated.status_code == 200
    completed_poll = await client.get(f"/api/jobs/{run_id}")
    assert completed_poll.json()["status"] == "completed"
    assert completed_poll.json()["response"].endswith("[1]")
    assert persistence.calls == ["prepare", "escalate", "deliver_reviewed"]
