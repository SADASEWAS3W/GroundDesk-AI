"""Customer-support use case spanning persistence, Graph, review, and delivery."""

from __future__ import annotations

import json
import time
from typing import Any, Protocol

from agents import RunContextWrapper

from agent.application.models import SupportBusinessContext, SupportRequest
from agent.graph import HIGH_RISK_TERMS, run_support_graph
from agent.review import ReviewRecord, RunStatus
from agent.tools.conversation import save_message
from agent.tools.customer import find_or_create_customer
from agent.tools.escalation import escalate_to_human
from agent.tools.metrics import log_metric
from agent.tools.response import send_response
from agent.tools.ticket import create_ticket, update_ticket


class SupportPersistenceError(RuntimeError):
    """Raised when a required CRM operation did not complete."""


class SupportPersistence(Protocol):
    async def prepare(self, request: SupportRequest) -> SupportBusinessContext: ...

    async def complete(
        self,
        business: SupportBusinessContext,
        answer: str,
        *,
        response_time_ms: int,
    ) -> None: ...

    async def escalate(
        self,
        business: SupportBusinessContext,
        reason: str,
        *,
        response_time_ms: int,
    ) -> None: ...

    async def deliver_reviewed(
        self,
        business: SupportBusinessContext,
        answer: str,
    ) -> None: ...

    async def fail(
        self,
        business: SupportBusinessContext,
        reason: str,
        *,
        response_time_ms: int,
    ) -> None: ...


class ToolBackedSupportPersistence:
    """Adapter that reuses the existing tool transaction and validation logic."""

    def __init__(self, context) -> None:
        self._context = context
        self._wrapper = RunContextWrapper(context=context)

    async def _invoke_required(self, tool, payload: dict[str, Any]) -> dict[str, Any]:
        raw = await tool.on_invoke_tool(self._wrapper, json.dumps(payload))
        result = json.loads(raw)
        if result.get("error"):
            raise SupportPersistenceError(result["error"])
        return result

    async def _invoke_best_effort(self, tool, payload: dict[str, Any]) -> None:
        try:
            await tool.on_invoke_tool(self._wrapper, json.dumps(payload))
        except Exception:
            return

    async def prepare(self, request: SupportRequest) -> SupportBusinessContext:
        customer = await self._invoke_required(find_or_create_customer, {
            "identifier_type": request.identifier_type,
            "identifier_value": request.identifier_value,
            "name": request.name,
        })
        lowered = request.message.casefold()
        category = "billing" if any(term in lowered for term in ("refund", "退款", "billing")) else "general"
        priority = "high" if category == "billing" or any(
            term in lowered for term in HIGH_RISK_TERMS
        ) else "medium"
        ticket = await self._invoke_required(create_ticket, {
            "customer_id": customer["customer_id"],
            "channel": request.channel,
            "category": category,
            "priority": priority,
        })
        business = SupportBusinessContext(
            customer_id=customer["customer_id"],
            ticket_id=ticket["ticket_id"],
            conversation_id=ticket["conversation_id"],
            channel=request.channel,
        )
        await self._invoke_required(save_message, {
            "conversation_id": business.conversation_id,
            "direction": "inbound",
            "channel": business.channel,
            "content": request.message,
            "sentiment": None,
        })
        await self._invoke_required(update_ticket, {
            "ticket_id": business.ticket_id,
            "status": "in_progress",
        })
        return business

    async def complete(
        self,
        business: SupportBusinessContext,
        answer: str,
        *,
        response_time_ms: int,
    ) -> None:
        await self._invoke_required(send_response, {
            "conversation_id": business.conversation_id,
            "channel": business.channel,
            "content": answer,
            "ticket_id": business.ticket_id,
        })
        await self._invoke_required(update_ticket, {
            "ticket_id": business.ticket_id,
            "status": "resolved",
            "resolution_notes": "Grounded answer delivered by the support workflow.",
        })
        await self._invoke_best_effort(log_metric, {
            "channel": business.channel,
            "response_time_ms": response_time_ms,
            "resolution_type": "auto_resolved",
            "customer_id": business.customer_id,
            "ticket_id": business.ticket_id,
        })

    async def escalate(
        self,
        business: SupportBusinessContext,
        reason: str,
        *,
        response_time_ms: int,
    ) -> None:
        await self._invoke_required(escalate_to_human, {
            "ticket_id": business.ticket_id,
            "reason": reason,
        })
        await self._invoke_best_effort(log_metric, {
            "channel": business.channel,
            "response_time_ms": response_time_ms,
            "resolution_type": "escalated",
            "customer_id": business.customer_id,
            "ticket_id": business.ticket_id,
            "escalation_reason": reason,
        })

    async def deliver_reviewed(
        self,
        business: SupportBusinessContext,
        answer: str,
    ) -> None:
        await self._invoke_required(send_response, {
            "conversation_id": business.conversation_id,
            "channel": business.channel,
            "content": answer,
            "ticket_id": business.ticket_id,
        })

    async def fail(
        self,
        business: SupportBusinessContext,
        reason: str,
        *,
        response_time_ms: int,
    ) -> None:
        await self._invoke_required(escalate_to_human, {
            "ticket_id": business.ticket_id,
            "reason": reason,
        })
        await self._invoke_best_effort(log_metric, {
            "channel": business.channel,
            "response_time_ms": response_time_ms,
            "resolution_type": "error",
            "customer_id": business.customer_id,
            "ticket_id": business.ticket_id,
            "escalation_reason": reason,
        })


class SupportApplicationService:
    """Single application entry point for Web and webhook support requests."""

    def __init__(self, context, *, persistence: SupportPersistence | None = None) -> None:
        self._context = context
        self._persistence = persistence or ToolBackedSupportPersistence(context)

    async def run(self, request: SupportRequest) -> dict[str, Any]:
        started = time.perf_counter()
        business = await self._persistence.prepare(request)
        try:
            state = await run_support_graph(self._context.support_graph, {
                "run_id": request.run_id,
                "conversation_id": business.conversation_id,
                "ticket_id": business.ticket_id,
                "original_query": request.message,
                "status": RunStatus.PROCESSING.value,
            })
        except Exception:
            elapsed_ms = max(0, round((time.perf_counter() - started) * 1000))
            await self._persistence.fail(
                business,
                "agent_workflow_failed",
                response_time_ms=elapsed_ms,
            )
            raise
        status = RunStatus(state.get("status", RunStatus.COMPLETED))
        elapsed_ms = max(0, round((time.perf_counter() - started) * 1000))

        if status == RunStatus.WAITING_REVIEW:
            reason = state.get("review_reason") or "manual_review_required"
            await self._persistence.escalate(
                business,
                reason,
                response_time_ms=elapsed_ms,
            )
            await self._context.review_repository.save(ReviewRecord(
                run_id=request.run_id,
                status=status,
                original_query=request.message,
                draft_answer=state.get("answer", ""),
                citations=state.get("citations", []),
                retrieved_document_ids=[
                    document["document_id"]
                    for document in state.get("retrieved_documents", [])
                ],
                review_reason=reason,
                customer_id=business.customer_id,
                conversation_id=business.conversation_id,
                ticket_id=business.ticket_id,
                channel=business.channel,
            ))
        elif status == RunStatus.COMPLETED:
            await self._persistence.complete(
                business,
                state.get("answer", ""),
                response_time_ms=elapsed_ms,
            )

        return {
            "run_id": request.run_id,
            "conversation_id": business.conversation_id,
            "ticket_id": business.ticket_id,
            "status": status,
            "response": state.get("answer", "") if status == RunStatus.COMPLETED else None,
            "citations": state.get("citations", []),
            "requires_human_review": status == RunStatus.WAITING_REVIEW,
            "review_reason": state.get("review_reason"),
        }

    async def deliver_reviewed(self, record: ReviewRecord, answer: str) -> None:
        if not record.customer_id or not record.ticket_id or not record.conversation_id:
            raise SupportPersistenceError("review record is missing business identifiers")
        await self._persistence.deliver_reviewed(
            SupportBusinessContext(
                customer_id=record.customer_id,
                ticket_id=record.ticket_id,
                conversation_id=record.conversation_id,
                channel=record.channel,
            ),
            answer,
        )
