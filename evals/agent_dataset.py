"""Validated, versioned Agent evaluation dataset loading."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ExpectedStatus = Literal["completed", "waiting_review", "failed"]

SCENARIOS = {
    "normal",
    "no_results",
    "low_confidence",
    "invalid_citation",
    "duplicate_citation",
    "missing_citation",
    "reranker_fallback",
    "rewrite_error",
    "generator_error",
}


@dataclass(frozen=True, slots=True)
class AgentEvalCase:
    case_id: str
    query: str
    expected_status: ExpectedStatus
    should_escalate: bool
    expected_document_titles: tuple[str, ...]
    tags: tuple[str, ...]
    scenario: str = "normal"
    split: str = "tuning"
    notes: str = ""


def load_agent_dataset(path: Path) -> list[AgentEvalCase]:
    cases: list[AgentEvalCase] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
            case = AgentEvalCase(
                case_id=item["id"].strip(),
                query=item["query"].strip(),
                expected_status=item["expected_status"],
                should_escalate=item["should_escalate"],
                expected_document_titles=tuple(item["expected_document_titles"]),
                tags=tuple(item.get("tags", [])),
                scenario=item.get("scenario", "normal"),
                split=item.get("split", "tuning"),
                notes=item.get("notes", ""),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid agent dataset row {line_number}") from exc
        if not case.case_id or not case.query:
            raise ValueError(f"agent dataset row {line_number} has an empty id or query")
        if case.case_id in seen_ids:
            raise ValueError(f"duplicate agent eval id: {case.case_id}")
        if case.expected_status not in {"completed", "waiting_review", "failed"}:
            raise ValueError(f"invalid expected status in case: {case.case_id}")
        if not isinstance(case.should_escalate, bool):
            raise ValueError(f"should_escalate must be boolean in case: {case.case_id}")
        if (case.expected_status == "waiting_review") != case.should_escalate:
            raise ValueError(f"inconsistent escalation label in case: {case.case_id}")
        if case.scenario not in SCENARIOS:
            raise ValueError(f"invalid scenario in case: {case.case_id}")
        if case.split not in {"tuning", "validation"}:
            raise ValueError(f"invalid agent eval split in case: {case.case_id}")
        if len(set(case.expected_document_titles)) != len(
            case.expected_document_titles
        ):
            raise ValueError(f"duplicate expected title in case: {case.case_id}")
        if case.scenario == "no_results" and case.expected_document_titles:
            raise ValueError(f"no_results case has expected documents: {case.case_id}")
        seen_ids.add(case.case_id)
        cases.append(case)
    if not cases:
        raise ValueError("agent dataset is empty")
    return cases
