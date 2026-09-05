"""Validated JSONL dataset loading."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RetrievalEvalCase:
    case_id: str
    query: str
    relevant_document_titles: tuple[str, ...]
    tags: tuple[str, ...]
    notes: str = ""
    split: str = "tuning"


def load_retrieval_dataset(path: Path) -> list[RetrievalEvalCase]:
    cases: list[RetrievalEvalCase] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
            case = RetrievalEvalCase(
                case_id=item["id"].strip(),
                query=item["query"].strip(),
                relevant_document_titles=tuple(item["relevant_document_titles"]),
                tags=tuple(item.get("tags", [])),
                notes=item.get("notes", ""),
                split=item.get("split", "tuning"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid dataset row {line_number}") from exc
        if not case.case_id or not case.query:
            raise ValueError(f"dataset row {line_number} has an empty id or query")
        if case.case_id in seen_ids:
            raise ValueError(f"duplicate eval id: {case.case_id}")
        if len(set(case.relevant_document_titles)) != len(case.relevant_document_titles):
            raise ValueError(f"duplicate relevant title in case: {case.case_id}")
        if case.split not in {"tuning", "validation", "test"}:
            raise ValueError(f"invalid eval split in case: {case.case_id}")
        seen_ids.add(case.case_id)
        cases.append(case)
    if not cases:
        raise ValueError("retrieval dataset is empty")
    return cases
