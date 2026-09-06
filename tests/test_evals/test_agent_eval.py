from pathlib import Path

import pytest

from evals.agent_eval import run_offline, summarize_agent_results


async def test_offline_agent_eval_runs_all_scenarios_without_provider_calls():
    report = await run_offline(Path("evals/datasets/agent_v1.jsonl"))
    metrics = report["metrics"]

    assert report["mode"] == "offline"
    assert metrics["evaluated_cases"] == 30
    assert metrics["expected_status_accuracy"] == 1.0
    assert metrics["correct_escalation_rate"] == 1.0
    assert metrics["high_risk_miss_rate"] == 0.0
    assert metrics["false_escalation_rate"] == 0.0
    assert metrics["failed_case_count"] == 0
    assert metrics["p95_latency_ms"] >= metrics["p50_latency_ms"] >= 0
    assert any(
        case["rewrite_fallback"] for case in metrics["case_results"]
    )
    assert any(
        case["reranker_fallback"] for case in metrics["case_results"]
    )


def test_agent_summary_rejects_empty_results():
    with pytest.raises(ValueError, match="empty"):
        summarize_agent_results([])
