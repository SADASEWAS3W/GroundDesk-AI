from pathlib import Path

import pytest

from evals.agent_dataset import load_agent_dataset


def test_agent_v1_dataset_has_30_balanced_cases():
    cases = load_agent_dataset(Path("evals/datasets/agent_v1.jsonl"))

    assert len(cases) == 30
    assert len({case.case_id for case in cases}) == 30
    assert sum(case.split == "tuning" for case in cases) == 20
    assert sum(case.split == "validation" for case in cases) == 10
    assert any("high_risk" in case.tags for case in cases)
    assert any(case.scenario == "no_results" for case in cases)
    assert any("citation" in case.scenario for case in cases)
    assert any(case.scenario == "generator_error" for case in cases)


def test_agent_dataset_rejects_invalid_scenario(tmp_path):
    path = tmp_path / "agent.jsonl"
    path.write_text(
        '{"id":"x","query":"q","expected_status":"completed",'
        '"should_escalate":false,"expected_document_titles":[],'
        '"scenario":"magic"}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid scenario"):
        load_agent_dataset(path)


def test_agent_dataset_rejects_non_boolean_escalation(tmp_path):
    path = tmp_path / "agent.jsonl"
    path.write_text(
        '{"id":"x","query":"q","expected_status":"completed",'
        '"should_escalate":"no","expected_document_titles":[]}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="should_escalate"):
        load_agent_dataset(path)
