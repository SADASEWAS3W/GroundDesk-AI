"""Run the customer-support LangGraph against offline or live dependencies."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from agent.context import build_context
from agent.graph import build_support_graph, initialize_support_graph, run_support_graph
from agent.nodes import GeneratedAnswer
from agent.retrieval import RetrievedDocument, RetrievalDiagnostics, RetrievalResult
from evals.agent_dataset import AgentEvalCase, load_agent_dataset
from evals.metrics import percentile


class _ScenarioRetrievalService:
    def __init__(self, case: AgentEvalCase) -> None:
        self._case = case

    async def retrieve(self, query: str, *, strategy="hybrid_rerank", top_k=3):
        if self._case.scenario == "no_results":
            return RetrievalResult(
                query=query,
                documents=[],
                strategy=strategy,
                low_confidence=True,
                confidence_reasons=["no_retrieval_results"],
                diagnostics=RetrievalDiagnostics(returned_count=0),
            )
        documents = [
            RetrievedDocument(
                document_id=f"doc-{self._case.case_id}-{index}",
                title=title,
                content=f"Verified support guidance for {title}.",
                source_retrievers=("vector", "bm25"),
                vector_score=0.85,
                final_rank=index,
            )
            for index, title in enumerate(
                self._case.expected_document_titles[:top_k], start=1
            )
        ]
        low_confidence = self._case.scenario == "low_confidence"
        return RetrievalResult(
            query=query,
            documents=documents,
            strategy=strategy,
            low_confidence=low_confidence,
            confidence_reasons=["vector_top1_below_threshold"] if low_confidence else [],
            diagnostics=RetrievalDiagnostics(
                returned_count=len(documents),
                reranker_fallback=self._case.scenario == "reranker_fallback",
                fallback_reason=(
                    "offline_simulated_reranker_error"
                    if self._case.scenario == "reranker_fallback"
                    else None
                ),
            ),
        )


class _ScenarioGenerator:
    def __init__(self, scenario: str) -> None:
        self._scenario = scenario

    async def generate(self, query: str, documents: list[dict[str, Any]]):
        if self._scenario == "generator_error":
            raise RuntimeError("offline simulated generation failure")
        first_id = documents[0]["document_id"]
        if self._scenario == "invalid_citation":
            return GeneratedAnswer("Unsupported answer [1]", ["unknown-document"])
        if self._scenario == "duplicate_citation":
            return GeneratedAnswer("Duplicated source [1]", [first_id, first_id])
        if self._scenario == "missing_citation":
            return GeneratedAnswer("Answer without a marker", [first_id])
        return GeneratedAnswer("Grounded support answer [1]", [first_id])


class _FailingRewriter:
    async def rewrite(self, query: str) -> str:
        raise RuntimeError("offline simulated rewrite failure")


async def _run_case(case: AgentEvalCase, graph) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        state = await run_support_graph(graph, {
            "run_id": f"eval-{case.case_id}",
            "conversation_id": f"eval-conversation-{case.case_id}",
            "original_query": case.query,
        })
        actual_status = state.get("status", "failed")
        citations = state.get("citations", [])
        retrieved_titles = [
            document["title"] for document in state.get("retrieved_documents", [])
        ]
        has_generated_evidence = bool(state.get("retrieved_documents"))
        citation_valid = (
            bool(citations) and not state.get("grounding_issues", [])
            if has_generated_evidence
            else None
        )
        grounded = state.get("grounded") if has_generated_evidence else None
        error_type = None
        review_reason = state.get("review_reason")
        grounding_issues = state.get("grounding_issues", [])
        rewrite_fallback = state.get("rewrite_fallback", False)
    except Exception as exc:
        actual_status = "failed"
        citations = []
        retrieved_titles = []
        citation_valid = None
        grounded = None
        error_type = type(exc).__name__
        review_reason = None
        grounding_issues = []
        rewrite_fallback = False
    latency_ms = (time.perf_counter() - started) * 1000
    actual_escalation = actual_status == "waiting_review"
    return {
        "id": case.case_id,
        "query": case.query,
        "expected_status": case.expected_status,
        "actual_status": actual_status,
        "should_escalate": case.should_escalate,
        "actual_escalation": actual_escalation,
        "status_correct": actual_status == case.expected_status,
        "escalation_correct": actual_escalation == case.should_escalate,
        "grounded": grounded,
        "citation_valid": citation_valid,
        "citation_count": len(citations),
        "expected_document_titles": list(case.expected_document_titles),
        "retrieved_document_titles": retrieved_titles,
        "expected_documents_retrieved": set(case.expected_document_titles).issubset(
            retrieved_titles
        ),
        "review_reason": review_reason,
        "grounding_issues": list(grounding_issues),
        "rewrite_fallback": rewrite_fallback,
        "reranker_fallback": case.scenario == "reranker_fallback",
        "error_type": error_type,
        "latency_ms": latency_ms,
        "scenario": case.scenario,
        "tags": list(case.tags),
        "split": case.split,
    }


def summarize_agent_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        raise ValueError("agent results are empty")

    def rate(matches, total) -> float:
        return matches / total if total else 0.0

    grounded = [item for item in results if item["grounded"] is not None]
    citation_scored = [item for item in results if item["citation_valid"] is not None]
    high_risk = [item for item in results if "high_risk" in item["tags"]]
    non_escalation = [item for item in results if not item["should_escalate"]]
    failures = []
    for item in results:
        reasons = []
        if not item["status_correct"]:
            reasons.append("status_mismatch")
        if not item["escalation_correct"]:
            reasons.append("escalation_mismatch")
        if (
            item["actual_status"] != "failed"
            and item["expected_document_titles"]
            and not item["expected_documents_retrieved"]
        ):
            reasons.append("expected_document_missing")
        if reasons:
            failures.append({
                "id": item["id"],
                "reasons": reasons,
                "expected_status": item["expected_status"],
                "actual_status": item["actual_status"],
                "review_reason": item["review_reason"],
                "grounding_issues": item["grounding_issues"],
            })
    latencies = [item["latency_ms"] for item in results]
    return {
        "evaluated_cases": len(results),
        "grounded_answer_rate": rate(
            sum(item["grounded"] is True for item in grounded), len(grounded)
        ),
        "correct_escalation_rate": rate(
            sum(item["escalation_correct"] for item in results), len(results)
        ),
        "citation_validity_rate": rate(
            sum(item["citation_valid"] is True for item in citation_scored),
            len(citation_scored),
        ),
        "expected_status_accuracy": rate(
            sum(item["status_correct"] for item in results), len(results)
        ),
        "high_risk_miss_rate": rate(
            sum(not item["actual_escalation"] for item in high_risk), len(high_risk)
        ),
        "false_escalation_rate": rate(
            sum(item["actual_escalation"] for item in non_escalation),
            len(non_escalation),
        ),
        "p50_latency_ms": percentile(latencies, 50),
        "p95_latency_ms": percentile(latencies, 95),
        "failed_case_count": len(failures),
        "failures": failures,
        "case_results": results,
    }


async def run_offline(dataset_path: Path) -> dict[str, Any]:
    cases = load_agent_dataset(dataset_path)
    results = []
    for case in cases:
        graph = build_support_graph(
            _ScenarioRetrievalService(case),
            query_rewriter=(
                _FailingRewriter() if case.scenario == "rewrite_error" else None
            ),
            answer_generator=_ScenarioGenerator(case.scenario),
        )
        results.append(await _run_case(case, graph))
    return {
        "mode": "offline",
        "dataset": str(dataset_path),
        "metrics": summarize_agent_results(results),
    }


async def run_live(dataset_path: Path) -> dict[str, Any]:
    cases = load_agent_dataset(dataset_path)
    synthetic_scenarios = {
        "invalid_citation",
        "duplicate_citation",
        "missing_citation",
        "reranker_fallback",
        "rewrite_error",
        "generator_error",
    }
    live_cases = [case for case in cases if case.scenario not in synthetic_scenarios]
    context = await build_context()
    try:
        graph = await initialize_support_graph(context)
        results = [await _run_case(case, graph) for case in live_cases]
        return {
            "mode": "live",
            "dataset": str(dataset_path),
            "skipped_synthetic_case_count": len(cases) - len(live_cases),
            "metrics": summarize_agent_results(results),
        }
    finally:
        if context.redis_client is not None:
            await context.redis_client.aclose()
        await context.db_pool.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("evals/datasets/agent_v1.jsonl"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evals/reports/agent-latest.json"),
    )
    parser.add_argument(
        "--execute-live",
        action="store_true",
        help="authorize real database, retrieval, rewrite, reranker, and generation calls",
    )
    args = parser.parse_args()
    load_dotenv()
    report = asyncio.run(
        run_live(args.dataset) if args.execute_live else run_offline(args.dataset)
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    console_metrics = {
        key: value
        for key, value in report["metrics"].items()
        if key != "case_results"
    }
    print(json.dumps(console_metrics | {"output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
