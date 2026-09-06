"""Minimal grounded LangGraph workflow around the unified retrieval service."""

from __future__ import annotations

import re
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from agent.retrieval import RetrievalService
from agent.state import SupportState
from agent.nodes import (
    AnswerGenerator,
    DeterministicQueryRewriter,
    ExtractiveAnswerGenerator,
    LLMAnswerGenerator,
    LLMQueryRewriter,
    QueryRewriter,
)

HIGH_RISK_TERMS = (
    "refund",
    "退款",
    "billing dispute",
    "chargeback",
    "账单争议",
    "legal",
    "法律",
    "lawyer",
    "lawsuit",
    "delete account",
    "delete my account",
    "delete the account",
    "account deletion",
    "close my account",
    "删除账户",
    "删除账号",
    "注销账户",
    "注销账号",
)
_CITATION_PATTERN = re.compile(r"\[(\d+)]")


def validate_answer_citations(
    answer: str,
    citations: list[dict[str, Any]],
) -> list[str]:
    """Return deterministic citation issues for a generated or edited answer."""
    allowed_indices = {int(item["index"]) for item in citations if "index" in item}
    used_indices = {int(value) for value in _CITATION_PATTERN.findall(answer)}
    issues: list[str] = []
    if allowed_indices and not used_indices:
        issues.append("missing_citation_markers")
    if not used_indices.issubset(allowed_indices):
        issues.append("invalid_citation_marker")
    if used_indices and allowed_indices - used_indices:
        issues.append("unused_citation_marker")
    return issues


async def initialize_support_graph(context):
    """Build the BM25 corpus and inject all provider/database dependencies."""
    from agent.retrieval import (
        HybridRetrievalService,
        CachedRetrievalService,
        InMemoryBM25Retriever,
        LLMReranker,
        PgVectorRetriever,
        ReciprocalRankFusion,
        load_knowledge_documents,
    )
    from agent.review import build_review_repository

    corpus = await load_knowledge_documents(context.db_pool)
    bm25 = InMemoryBM25Retriever()
    bm25.build(corpus)
    service = HybridRetrievalService(
        vector_retriever=PgVectorRetriever(
            model_client=context.model_client,
            db_pool=context.db_pool,
        ),
        bm25_retriever=bm25,
        fusion_strategy=ReciprocalRankFusion(),
        reranker=LLMReranker(model_client=context.model_client),
    )
    context.retrieval_service = (
        CachedRetrievalService(service, context.redis_client)
        if context.redis_client is not None
        else service
    )
    context.support_graph = build_support_graph(
        context.retrieval_service,
        query_rewriter=LLMQueryRewriter(context.model_client),
        answer_generator=LLMAnswerGenerator(context.model_client),
    )
    context.review_repository = build_review_repository(context.redis_client)
    return context.support_graph


def _serialize_document(document: Any) -> dict[str, Any]:
    return {
        "document_id": document.document_id,
        "title": document.title,
        "content": document.content,
        "category": document.category,
        "source_retrievers": list(document.source_retrievers),
        "vector_score": document.vector_score,
        "bm25_score": document.bm25_score,
        "rrf_score": document.rrf_score,
        "rerank_score": document.rerank_score,
        "final_rank": document.final_rank,
    }


def build_support_graph(
    retrieval_service: RetrievalService,
    *,
    query_rewriter: QueryRewriter | None = None,
    answer_generator: AnswerGenerator | None = None,
):
    rewriter = query_rewriter or DeterministicQueryRewriter()
    generator = answer_generator or ExtractiveAnswerGenerator()

    async def rewrite_query(state: SupportState) -> dict[str, Any]:
        try:
            rewritten = await rewriter.rewrite(state["original_query"])
            return {"rewritten_query": rewritten, "rewrite_fallback": False}
        except Exception:
            return {
                "rewritten_query": " ".join(state["original_query"].strip().split()),
                "rewrite_fallback": True,
                "rewrite_issue": "query_rewrite_fallback",
            }

    async def retrieve(state: SupportState) -> dict[str, Any]:
        result = await retrieval_service.retrieve(
            state["rewritten_query"], strategy="hybrid_rerank", top_k=3
        )
        return {
            "retrieved_documents": [_serialize_document(doc) for doc in result.documents],
            "low_confidence": result.low_confidence,
            "confidence_reasons": list(result.confidence_reasons),
        }

    async def generate(state: SupportState) -> dict[str, Any]:
        documents = state.get("retrieved_documents", [])
        if not documents:
            return {
                "answer": "知识库中没有足够依据回答该问题。",
                "citations": [],
                "generated_citation_document_ids": [],
            }
        generated = await generator.generate(state["original_query"], documents)
        reported_ids = generated.citation_document_ids
        reported_id_set = set(reported_ids)
        citations = []
        for index, document in enumerate(documents, 1):
            if document["document_id"] not in reported_id_set:
                continue
            excerpt = " ".join(document["content"].split())[:280]
            citations.append({
                "index": index,
                "document_id": document["document_id"],
                "title": document["title"],
                "excerpt": excerpt,
            })
        return {
            "answer": generated.answer,
            "citations": citations,
            "generated_citation_document_ids": reported_ids,
        }

    async def grounding_check(state: SupportState) -> dict[str, Any]:
        document_ids = {doc["document_id"] for doc in state.get("retrieved_documents", [])}
        citation_ids = {citation["document_id"] for citation in state.get("citations", [])}
        reported_ids = state.get("generated_citation_document_ids", [])
        reported_id_set = set(reported_ids)
        issues = []
        if not document_ids:
            issues.append("no_retrieval_results")
        if not citation_ids:
            issues.append("missing_citations")
        if not citation_ids.issubset(document_ids):
            issues.append("invalid_citation_source")
        if len(reported_ids) != len(reported_id_set):
            issues.append("duplicate_citation_source")
        if not reported_id_set.issubset(document_ids):
            issues.append("invalid_reported_citation_source")
        if reported_id_set != citation_ids:
            issues.append("citation_source_mismatch")
        issues.extend(validate_answer_citations(
            state.get("answer", ""),
            state.get("citations", []),
        ))
        high_risk = any(term in state["original_query"].casefold() for term in HIGH_RISK_TERMS)
        requires_review = bool(issues or state.get("low_confidence") or high_risk)
        reason = (
            "high_risk_request" if high_risk else
            ",".join(state.get("confidence_reasons", []) or issues) or None
        )
        return {
            "grounded": not issues,
            "grounding_issues": issues,
            "requires_human_review": requires_review,
            "review_reason": reason,
            "status": "waiting_review" if requires_review else "completed",
        }

    async def human_review(state: SupportState) -> dict[str, Any]:
        decision = interrupt({
            "answer": state.get("answer", ""),
            "citations": state.get("citations", []),
            "reason": state.get("review_reason"),
        })
        action = decision.get("action", "reject")
        if action == "approve":
            return {"review_decision": decision, "status": "completed"}
        if action == "edit" and decision.get("answer"):
            return {
                "answer": decision["answer"],
                "review_decision": decision,
                "status": "completed",
            }
        return {"review_decision": decision, "answer": "", "status": "rejected"}

    def route_review(state: SupportState) -> str:
        return "human_review" if state.get("requires_human_review") else END

    graph = StateGraph(SupportState)
    graph.add_node("rewrite_query", rewrite_query)
    graph.add_node("retrieve", retrieve)
    graph.add_node("generate", generate)
    graph.add_node("grounding_check", grounding_check)
    graph.add_node("human_review", human_review)
    graph.add_edge(START, "rewrite_query")
    graph.add_edge("rewrite_query", "retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", "grounding_check")
    graph.add_conditional_edges("grounding_check", route_review)
    graph.add_edge("human_review", END)
    return graph.compile(checkpointer=InMemorySaver())


async def run_support_graph(graph, state: SupportState) -> SupportState:
    config = {"configurable": {"thread_id": state["run_id"]}}
    return await graph.ainvoke(state, config=config)


async def resume_support_graph(graph, run_id: str, decision: dict[str, Any]) -> SupportState:
    config = {"configurable": {"thread_id": run_id}}
    return await graph.ainvoke(Command(resume=decision), config=config)
