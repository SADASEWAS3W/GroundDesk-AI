"""FastAPI backend — thin HTTP layer over the Customer Success Agent."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import Literal

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from agents import RunContextWrapper

from agent import get_correlation_id, set_correlation_id
from agent.application import SupportApplicationService, SupportRequest
from agent.cache import get_job, set_job
from agent.context import build_context
from agent.customer_success_agent import run_agent
from agent.graph import (
    initialize_support_graph,
    resume_support_graph,
    run_support_graph,
    validate_answer_citations,
)
from agent.review import (
    ReviewAction,
    ReviewRecord,
    RunStatus,
    build_review_repository,
)
from agent.tools.customer import get_customer_history
from agent.tools.ticket import get_ticket

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str
    email: str
    channel: Literal["web", "gmail", "whatsapp"] = "web"
    name: str | None = None


class ChatResponse(BaseModel):
    response: str | None
    correlation_id: str
    run_id: str
    conversation_id: str | None = None
    ticket_id: str | None = None
    status: RunStatus = RunStatus.COMPLETED
    citations: list[dict] = Field(default_factory=list)
    requires_human_review: bool = False
    review_reason: str | None = None


class JobAccepted(BaseModel):
    job_id: str
    run_id: str
    status: RunStatus = RunStatus.PROCESSING
    retry_after: int = 5


class JobStatus(BaseModel):
    job_id: str
    run_id: str
    conversation_id: str | None = None
    ticket_id: str | None = None
    status: RunStatus
    response: str | None = None
    error: str | None = None
    retry_after: int | None = None
    citations: list[dict] = Field(default_factory=list)
    requires_human_review: bool = False
    review_reason: str | None = None


class ReviewDecision(BaseModel):
    action: ReviewAction
    answer: str | None = None

    @model_validator(mode="after")
    def validate_edit_answer(self):
        if self.action == ReviewAction.EDIT and not (self.answer or "").strip():
            raise ValueError("answer is required for edit")
        return self


class ReviewDetail(BaseModel):
    run_id: str
    status: RunStatus
    original_query: str
    draft_answer: str
    citations: list[dict] = Field(default_factory=list)
    review_reason: str | None = None
    conversation_id: str | None = None
    ticket_id: str | None = None
    final_answer: str | None = None
    decision_action: ReviewAction | None = None


class ReviewList(BaseModel):
    reviews: list[ReviewDetail] = Field(default_factory=list)


class WebhookPayload(BaseModel):
    from_address: str
    body: str


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv()
    app.state.agent_ctx = await build_context()
    await initialize_support_graph(app.state.agent_ctx)
    app.state.agent_ctx.support_service = SupportApplicationService(app.state.agent_ctx)
    logger.info("Agent context created — DB pool, OpenAI client, and Redis ready")
    yield
    if app.state.agent_ctx.redis_client is not None:
        await app.state.agent_ctx.redis_client.aclose()
        logger.info("Redis connection closed")
    await app.state.agent_ctx.db_pool.close()
    logger.info("DB pool closed")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="CRM Digital FTE API",
    description="HTTP layer for the Customer Success Agent",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error"},
    )


# ---------------------------------------------------------------------------
# Background task helpers
# ---------------------------------------------------------------------------


def _get_review_repository(ctx):
    repository = getattr(ctx, "review_repository", None)
    if repository is None:
        repository = build_review_repository(getattr(ctx, "redis_client", None))
        ctx.review_repository = repository
    return repository


def _review_detail(record: ReviewRecord) -> ReviewDetail:
    return ReviewDetail(
        run_id=record.run_id,
        status=record.status,
        original_query=record.original_query,
        draft_answer=record.draft_answer,
        citations=record.citations,
        review_reason=record.review_reason,
        conversation_id=record.conversation_id,
        ticket_id=record.ticket_id,
        final_answer=record.final_answer,
        decision_action=record.decision_action,
    )


def _job_status_from_record(record: ReviewRecord) -> JobStatus:
    return JobStatus(
        job_id=record.run_id,
        run_id=record.run_id,
        conversation_id=record.conversation_id,
        ticket_id=record.ticket_id,
        status=record.status,
        response=record.final_answer if record.status == RunStatus.COMPLETED else None,
        citations=record.citations,
        requires_human_review=record.status == RunStatus.WAITING_REVIEW,
        review_reason=record.review_reason,
    )


async def _run_workflow(
    job_id: str,
    message: str,
    ctx,
    *,
    identifier_value: str | None = None,
    channel: str = "web",
    name: str | None = None,
) -> dict:
    if getattr(ctx, "support_service", None) is not None and identifier_value:
        return await ctx.support_service.run(SupportRequest(
            run_id=job_id,
            message=message,
            identifier_value=identifier_value,
            channel=channel,
            name=name,
        ))
    if getattr(ctx, "support_graph", None) is None:
        legacy_message = (
            f"[Customer: {identifier_value}, Channel: {channel}] {message}"
            if identifier_value
            else message
        )
        return {
            "run_id": job_id,
            "status": RunStatus.COMPLETED,
            "response": await run_agent(ctx, legacy_message),
        }
    query = message.split("] ", 1)[-1] if message.startswith("[") else message
    state = await run_support_graph(ctx.support_graph, {
        "run_id": job_id,
        "conversation_id": job_id,
        "original_query": query,
        "status": "processing",
    })
    status = RunStatus(state.get("status", RunStatus.COMPLETED))
    if status == RunStatus.WAITING_REVIEW:
        await _get_review_repository(ctx).save(ReviewRecord(
            run_id=job_id,
            status=status,
            original_query=query,
            draft_answer=state.get("answer", ""),
            citations=state.get("citations", []),
            retrieved_document_ids=[
                document["document_id"]
                for document in state.get("retrieved_documents", [])
            ],
            review_reason=state.get("review_reason"),
            conversation_id=state.get("conversation_id"),
            ticket_id=state.get("ticket_id"),
        ))
    return {
        "run_id": job_id,
        "conversation_id": state.get("conversation_id"),
        "ticket_id": state.get("ticket_id"),
        "status": status,
        "response": state.get("answer", "") if status == RunStatus.COMPLETED else None,
        "citations": state.get("citations", []),
        "requires_human_review": status == RunStatus.WAITING_REVIEW,
        "review_reason": state.get("review_reason"),
    }


async def _process_chat(
    job_id: str,
    message: str,
    identifier_value: str,
    channel: str,
    name: str | None,
    ctx,
) -> None:
    """Run the agent in the background and store the result as a job."""
    set_correlation_id(job_id)
    logger.info("Job %s started — background processing", job_id)
    try:
        result = await _run_workflow(
            job_id,
            message,
            ctx,
            identifier_value=identifier_value,
            channel=channel,
            name=name,
        )
        await set_job(ctx.redis_client, job_id, result)
        logger.info("Job %s reached status %s", job_id, result["status"])
    except Exception as exc:
        logger.exception("Job %s failed — %s", job_id, exc)
        await set_job(ctx.redis_client, job_id, {
            "status": "failed",
            "response": None,
            "error": "An error occurred while processing your request. Please try again.",
        })


async def _process_webhook(job_id: str, channel: str, from_address: str, body: str, ctx) -> None:
    """Run the agent in the background for a webhook request."""
    set_correlation_id(job_id)
    logger.info("Job %s started — %s webhook processing", job_id, channel)
    try:
        result = await _run_workflow(
            job_id,
            body,
            ctx,
            identifier_value=from_address,
            channel=channel,
        )
        await set_job(ctx.redis_client, job_id, result)
        logger.info("Job %s completed — %s response stored", job_id, channel)
    except Exception as exc:
        logger.exception("Job %s failed — %s — %s", job_id, channel, exc)
        await set_job(ctx.redis_client, job_id, {
            "status": "failed",
            "response": None,
            "error": "An error occurred while processing your request. Please try again.",
        })


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/health/live")
async def health_live():
    """Liveness probe — is the process alive? No dependency checks."""
    return {"status": "alive"}


@app.get("/health/ready")
async def health_ready(request: Request):
    """Readiness probe — can this instance serve traffic?

    Checks asyncpg pool and Redis connectivity.
    Returns 200 if all dependencies are connected, 503 otherwise.
    """
    db_status = "disconnected"
    redis_status = "disconnected"

    ctx = request.app.state.agent_ctx

    # Check database (asyncpg pool)
    try:
        await ctx.db_pool.fetchval("SELECT 1")
        db_status = "connected"
    except Exception:
        pass

    # Check Redis
    try:
        if ctx.redis_client is not None:
            await ctx.redis_client.ping()
            redis_status = "connected"
    except Exception:
        pass

    is_ready = db_status == "connected" and redis_status == "connected"
    status_code = 200 if is_ready else 503

    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if is_ready else "not_ready",
            "database": db_status,
            "redis": redis_status,
        },
    )


@app.post("/api/chat")
async def chat(
    req: ChatRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    sync: bool = Query(False),
):
    cid = set_correlation_id()
    logger.info("Chat request — email=%s channel=%s", req.email, req.channel)

    ctx = request.app.state.agent_ctx

    # Sync mode: explicit ?sync=true OR graceful fallback when Redis is unavailable
    if sync or ctx.redis_client is None:
        if ctx.redis_client is None and not sync:
            logger.warning("Redis unavailable — falling back to sync mode")
        result = await _run_workflow(
            cid,
            req.message,
            ctx,
            identifier_value=req.email,
            channel=req.channel,
            name=req.name,
        )
        return ChatResponse(correlation_id=cid, **result)

    # Async mode (default)
    await set_job(ctx.redis_client, cid, {"status": "processing"})
    background_tasks.add_task(
        _process_chat,
        cid,
        req.message,
        req.email,
        req.channel,
        req.name,
        ctx,
    )
    return JSONResponse(
        status_code=202,
        content=JobAccepted(job_id=cid, run_id=cid).model_dump(mode="json"),
    )


@app.get("/api/jobs/{job_id}", response_model=JobStatus)
async def job_status(job_id: str, request: Request):
    ctx = request.app.state.agent_ctx
    data = await get_job(ctx.redis_client, job_id)
    if data is None:
        review_record = await _get_review_repository(ctx).get(job_id)
        if review_record is not None:
            return _job_status_from_record(review_record)
        return JSONResponse(status_code=404, content={"error": "Job not found"})

    status = RunStatus(data["status"])
    retry = 5 if status == RunStatus.PROCESSING else None
    return JobStatus(
        job_id=job_id,
        run_id=data.get("run_id", job_id),
        conversation_id=data.get("conversation_id"),
        ticket_id=data.get("ticket_id"),
        status=status,
        response=None if status == RunStatus.WAITING_REVIEW else data.get("response"),
        error=data.get("error"),
        retry_after=retry,
        citations=data.get("citations", []),
        requires_human_review=data.get("requires_human_review", False),
        review_reason=data.get("review_reason"),
    )


@app.get("/api/reviews", response_model=ReviewList)
async def list_reviews(request: Request):
    records = await _get_review_repository(request.app.state.agent_ctx).list_pending()
    return ReviewList(reviews=[_review_detail(record) for record in records])


@app.get("/api/reviews/{run_id}", response_model=ReviewDetail)
async def review_detail(run_id: str, request: Request):
    record = await _get_review_repository(request.app.state.agent_ctx).get(run_id)
    if record is None:
        return JSONResponse(status_code=404, content={"error": "Review not found"})
    return _review_detail(record)


@app.post("/api/reviews/{run_id}", response_model=JobStatus)
async def review_run(run_id: str, decision: ReviewDecision, request: Request):
    ctx = request.app.state.agent_ctx
    repository = _get_review_repository(ctx)
    record = await repository.get(run_id)
    if record is None:
        return JSONResponse(status_code=404, content={"error": "Review not found"})

    if record.status in {RunStatus.COMPLETED, RunStatus.REJECTED}:
        same_action = record.decision_action == decision.action
        same_answer = (
            decision.action != ReviewAction.EDIT
            or record.decision_answer == decision.answer
        )
        if same_action and same_answer:
            return _job_status_from_record(record)
        return JSONResponse(
            status_code=409,
            content={"error": "Review already finalized with a different decision"},
        )
    if record.status != RunStatus.WAITING_REVIEW:
        return JSONResponse(status_code=409, content={"error": "Review is not pending"})

    if decision.action == ReviewAction.EDIT:
        citation_issues = validate_answer_citations(
            decision.answer or "",
            record.citations,
        )
        if citation_issues:
            return JSONResponse(
                status_code=422,
                content={
                    "error": "Edited answer failed citation validation",
                    "issues": citation_issues,
                },
            )

    try:
        state = await resume_support_graph(
            ctx.support_graph,
            run_id,
            {"action": decision.action.value, "answer": decision.answer},
        )
    except Exception:
        logger.exception("Failed to resume review run %s", run_id)
        return JSONResponse(
            status_code=409,
            content={"error": "Review checkpoint is unavailable"},
        )

    status = RunStatus(state.get("status", RunStatus.COMPLETED))
    final_answer = state.get("answer") if status == RunStatus.COMPLETED else None
    if status == RunStatus.COMPLETED and final_answer and getattr(ctx, "support_service", None):
        await ctx.support_service.deliver_reviewed(record, final_answer)
    record = record.with_decision(
        action=decision.action,
        status=status,
        final_answer=final_answer,
        decision_answer=decision.answer,
    )
    await repository.save(record)
    result = {
        "run_id": run_id,
        "conversation_id": record.conversation_id,
        "ticket_id": record.ticket_id,
        "status": status,
        "response": final_answer,
        "citations": state.get("citations", []),
        "requires_human_review": False,
        "review_reason": state.get("review_reason"),
    }
    await set_job(ctx.redis_client, run_id, result)
    return JobStatus(job_id=run_id, **result)


@app.get("/api/tickets/{ticket_id}")
async def ticket_detail(ticket_id: str, request: Request):
    set_correlation_id()
    wrapper = RunContextWrapper(context=request.app.state.agent_ctx)
    result = await get_ticket.on_invoke_tool(wrapper, json.dumps({"ticket_id": ticket_id}))
    data = json.loads(result)

    if "error" in data and data["error"] == "ticket not found":
        return JSONResponse(status_code=404, content={"error": "ticket not found"})

    return data


@app.get("/api/customers/{customer_id}/history")
async def customer_history(customer_id: str, request: Request):
    set_correlation_id()
    wrapper = RunContextWrapper(context=request.app.state.agent_ctx)
    result = await get_customer_history.on_invoke_tool(
        wrapper, json.dumps({"customer_id": customer_id})
    )
    data = json.loads(result)

    if "error" in data and data["error"] == "customer not found":
        return JSONResponse(status_code=404, content={"error": "customer not found"})

    return data


@app.post("/api/webhooks/gmail")
async def webhook_gmail(payload: WebhookPayload, request: Request, background_tasks: BackgroundTasks):
    cid = set_correlation_id()
    logger.info("Gmail webhook — from=%s", payload.from_address)

    ctx = request.app.state.agent_ctx

    if ctx.redis_client is None:
        logger.warning("Redis unavailable — falling back to sync mode (gmail)")
        result = await _run_workflow(
            cid,
            payload.body,
            ctx,
            identifier_value=payload.from_address,
            channel="gmail",
        )
        return ChatResponse(correlation_id=cid, **result)

    await set_job(ctx.redis_client, cid, {"status": "processing"})
    background_tasks.add_task(_process_webhook, cid, "gmail", payload.from_address, payload.body, ctx)
    return JSONResponse(
        status_code=202,
        content=JobAccepted(job_id=cid, run_id=cid).model_dump(mode="json"),
    )


@app.post("/api/webhooks/whatsapp")
async def webhook_whatsapp(payload: WebhookPayload, request: Request, background_tasks: BackgroundTasks):
    cid = set_correlation_id()
    logger.info("WhatsApp webhook — from=%s", payload.from_address)

    ctx = request.app.state.agent_ctx

    if ctx.redis_client is None:
        logger.warning("Redis unavailable — falling back to sync mode (whatsapp)")
        result = await _run_workflow(
            cid,
            payload.body,
            ctx,
            identifier_value=payload.from_address,
            channel="whatsapp",
        )
        return ChatResponse(correlation_id=cid, **result)

    await set_job(ctx.redis_client, cid, {"status": "processing"})
    background_tasks.add_task(_process_webhook, cid, "whatsapp", payload.from_address, payload.body, ctx)
    return JSONResponse(
        status_code=202,
        content=JobAccepted(job_id=cid, run_id=cid).model_dump(mode="json"),
    )
