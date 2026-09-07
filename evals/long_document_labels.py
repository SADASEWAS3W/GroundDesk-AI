"""Offline, source-stable labels for whole-document/chunk comparisons.

Evidence quotes are authored labels, never inserted into the searchable corpus.
Character offsets refer to normalized UTF-8 text read by the ingestion CLI.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from agent.retrieval.ingest import prepare_source
from agent.retrieval.models import RetrievedDocument, validate_top_k
from evals.metrics import recall_at_k, reciprocal_rank

DEFAULT_MANIFEST = Path("evals/corpus/long_v1/manifest.json")
DEFAULT_DATASET = Path("evals/datasets/retrieval_long_v1.jsonl")
WHOLE_CHUNK_SIZE = 100_000


@dataclass(frozen=True)
class Evidence:
    source_id: str
    start: int
    end: int


@dataclass(frozen=True)
class LongDocumentCase:
    case_id: str
    query: str
    split: str
    group_id: str
    tags: tuple[str, ...]
    evidence: tuple[Evidence, ...]


@dataclass
class LongDocumentBenchmark:
    version: str
    fingerprint: str
    variant: str
    sources: dict[str, dict]
    cases: list[LongDocumentCase]
    documents: list[RetrievedDocument]
    # Authoritative mapping built from the same source_id and offsets as ingestion.
    fragments: dict[str, Evidence]
    imports: list[tuple[dict, list[dict]]]

    def validate_corpus(self, actual: list[RetrievedDocument]) -> None:
        expected = {doc.document_id: doc for doc in self.documents}
        if len(actual) != len(expected) or {doc.document_id for doc in actual} != set(expected):
            raise ValueError("evaluation database must contain exactly this corpus variant")
        if any((doc.title, doc.content, doc.category) != (
            expected[doc.document_id].title, expected[doc.document_id].content,
            expected[doc.document_id].category,
        ) for doc in actual):
            raise ValueError("database content differs from the labelled corpus")


def _nonempty(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def load_benchmark(
    manifest_path: Path = DEFAULT_MANIFEST,
    dataset_path: Path = DEFAULT_DATASET,
    *, variant: str = "chunked", chunk_size: int = 1200, overlap: int = 150,
) -> LongDocumentBenchmark:
    if variant not in {"whole", "chunked"}:
        raise ValueError("variant must be whole or chunked")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "synthetic-review-required":
        raise ValueError("corpus must declare synthetic-review-required status")
    sources: dict[str, dict] = {}
    root = manifest_path.parent.resolve()
    source_items = manifest.get("sources")
    if not isinstance(source_items, list) or not source_items:
        raise ValueError("manifest sources must be a non-empty list")
    for item in source_items:
        source_id = _nonempty(item["source_id"], "source_id")
        if source_id in sources:
            raise ValueError(f"duplicate source_id: {source_id}")
        path = (root / _nonempty(item["path"], "source path")).resolve()
        if not path.is_relative_to(root):
            raise ValueError("source path must stay within corpus directory")
        content = path.read_text(encoding="utf-8-sig")
        if not content.strip() or len(content) > WHOLE_CHUNK_SIZE:
            raise ValueError("source must be nonblank and fit the whole-document variant")
        if item["split"] not in {"tuning", "validation", "test"}:
            raise ValueError("invalid source split")
        sources[source_id] = {**item, "content": content}

    cases = []
    seen_ids: set[str] = set()
    seen_queries: set[str] = set()
    group_splits: dict[str, str] = {}
    for line in dataset_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        case_id = _nonempty(item["id"], "case id")
        query = _nonempty(item["query"], "query")
        query_key = " ".join(query.casefold().split())
        if case_id in seen_ids or query_key in seen_queries:
            raise ValueError("duplicate case id or query")
        seen_ids.add(case_id)
        seen_queries.add(query_key)
        split = item["split"]
        if split not in {"tuning", "validation", "test"}:
            raise ValueError("invalid case split")
        group_id = _nonempty(item["group_id"], "group_id")
        if group_splits.setdefault(group_id, split) != split:
            raise ValueError("query group leaks across splits")
        evidence = []
        if not isinstance(item["evidence"], list):
            raise ValueError("evidence must be a list; use [] for no-answer cases")
        for label in item["evidence"]:
            source = sources.get(label["source_id"])
            if source is None:
                raise ValueError("evidence references unknown source")
            if source["split"] != split:
                raise ValueError("source labels leak across splits")
            quote = _nonempty(label["quote"], "evidence quote")
            if source["content"].count(quote) != 1:
                raise ValueError(f"evidence quote must occur exactly once: {case_id}")
            start = source["content"].index(quote)
            span = Evidence(label["source_id"], start, start + len(quote))
            if span in evidence:
                raise ValueError("duplicate evidence in case")
            evidence.append(span)
        tags = item.get("tags", [])
        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
            raise ValueError("tags must be a list of strings")
        if (not evidence) != ("no-answer" in tags):
            raise ValueError("no-answer tag must agree with empty evidence")
        cases.append(LongDocumentCase(case_id, query, split, group_id, tuple(tags), tuple(evidence)))
    if not cases:
        raise ValueError("dataset is empty")

    documents, fragments, imports = [], {}, []
    for source_id, item in sources.items():
        source, rows = prepare_source(
            item["content"], source_id=source_id, title=item["title"], category=item["category"],
            chunk_size=WHOLE_CHUNK_SIZE if variant == "whole" else chunk_size,
            overlap=0 if variant == "whole" else overlap,
        )
        imports.append((source, rows))
        for row in rows:
            document_id = str(row["id"])
            documents.append(RetrievedDocument(
                document_id=document_id, title=row["title"], content=row["content"],
                category=item["category"],
            ))
            fragments[document_id] = Evidence(source_id, row["start"], row["end"])
    # Same fingerprint for both variants, including query labels and source text.
    payload = json.dumps({"manifest": manifest, "sources": sources,
                          "dataset": dataset_path.read_text(encoding="utf-8")}, sort_keys=True)
    return LongDocumentBenchmark(
        manifest["version"], hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        variant, sources, cases, documents, fragments, imports,
    )


def contains(fragment: Evidence, label: Evidence) -> bool:
    return fragment.source_id == label.source_id and fragment.start <= label.start and fragment.end >= label.end


def score_case(
    case: LongDocumentCase, predicted: list[str], fragments: dict[str, Evidence], *, k: int = 3,
) -> dict:
    """Keep original ranks/slots; do NOT compress repeated source IDs before scoring.

    Evidence recall uses stable evidence spans as denominator, not overlapping
    chunk count. Chunk recall is diagnostic and is not comparable across sizes.
    A required span split across chunks is conservatively not covered unless one
    retrieved chunk contains it in full. This rule is explicit and deterministic.
    """
    validate_top_k(k)
    if len(predicted) != len(set(predicted)) or any(doc_id not in fragments for doc_id in predicted):
        raise ValueError("predictions must be unique known document IDs")
    if not case.evidence:
        return {name: None for name in (
            "source_recall_at_k", "source_mrr", "evidence_recall_at_k", "evidence_mrr",
            "chunk_recall_at_k", "all_evidence_covered_at_k",
        )}
    selected = predicted[:k]
    relevant_sources = {label.source_id for label in case.evidence}
    source_predictions = [fragments[doc_id].source_id for doc_id in selected]
    covered = {
        index for index, label in enumerate(case.evidence)
        if any(contains(fragments[doc_id], label) for doc_id in selected)
    }
    relevant_chunks = {
        doc_id for doc_id, fragment in fragments.items()
        if any(contains(fragment, label) for label in case.evidence)
    }
    return {
        "source_recall_at_k": recall_at_k(relevant_sources, source_predictions, k=k),
        "source_mrr": reciprocal_rank(relevant_sources, source_predictions),
        "evidence_recall_at_k": len(covered) / len(case.evidence),
        "evidence_mrr": reciprocal_rank(relevant_chunks, selected) if relevant_chunks else 0.0,
        "chunk_recall_at_k": recall_at_k(relevant_chunks, selected, k=k) if relevant_chunks else 0.0,
        "all_evidence_covered_at_k": float(len(covered) == len(case.evidence)),
    }
