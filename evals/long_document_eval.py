"""Isolated whole-document/chunk evaluation; preview/BM25 are entirely offline."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path

from agent.retrieval import (
    HybridRetrievalService, InMemoryBM25Retriever, LLMReranker,
    PgVectorRetriever, ReciprocalRankFusion, VectorRetrievalError, load_knowledge_documents,
)
from agent.retrieval.confidence import DEFAULT_MIN_TOP1_VECTOR_SCORE, RetrievalConfidencePolicy
from agent.retrieval.ingest import embed_chunks
from agent.retrieval.vector import DEFAULT_EMBEDDING_MODEL, EMBEDDING_DIMENSIONS
from database.knowledge_ingestion import insert_source
from database.pool import create_pool
from evals.long_document_labels import (
    DEFAULT_DATASET, DEFAULT_MANIFEST, LongDocumentBenchmark, contains, load_benchmark, score_case,
)
from evals.metrics import percentile


def preview(benchmark: LongDocumentBenchmark) -> dict:
    return {
        "corpus_version": benchmark.version, "corpus_fingerprint": benchmark.fingerprint,
        "status": "synthetic-review-required", "variant": benchmark.variant,
        "source_count": len(benchmark.sources), "document_count": len(benchmark.documents),
        "case_count": len(benchmark.cases),
        "answerable_count": sum(bool(case.evidence) for case in benchmark.cases),
        "splits": {split: sum(case.split == split for case in benchmark.cases)
                   for split in ("tuning", "validation", "test")},
        "sources": [{"source_id": source["source_id"], "characters": len(benchmark.sources[source["source_id"]]["content"]),
                     "chunks": len(rows), "chunk_size": source["chunk_size"], "overlap": source["overlap"]}
                    for source, rows in benchmark.imports],
        "uncoverable_evidence": [
            {"case_id": case.case_id, "source_id": label.source_id, "start": label.start, "end": label.end}
            for case in benchmark.cases for label in case.evidence
            if not any(contains(fragment, label) for fragment in benchmark.fragments.values())
        ],
    }


def summarize(rows: list[dict], *, accepted: bool = False) -> dict:
    successful = [row for row in rows if "error_type" not in row]
    answerable = [row for row in successful if row["answerable"]]
    key = "accepted" if accepted else "raw"
    metrics = {name: (sum(row[key][name] for row in answerable) / len(answerable)
                      if answerable else None)
               for name in ("source_recall_at_k", "source_mrr", "evidence_recall_at_k",
                            "evidence_mrr", "chunk_recall_at_k", "all_evidence_covered_at_k")}
    gated = [row for row in successful if row["low_confidence"] is not None]
    no_answer = [row for row in gated if not row["answerable"]]
    answerable_gated = [row for row in gated if row["answerable"]]
    rejected = [row for row in gated if row["low_confidence"]]
    correct_rejections = sum(not row["answerable"] for row in rejected)
    return {
        **metrics, "total_cases": len(rows), "successful_cases": len(successful),
        "operational_failure_count": len(rows) - len(successful),
        "no_answer_precision": correct_rejections / len(rejected) if rejected else None,
        "no_answer_recall": correct_rejections / len(no_answer) if no_answer else None,
        "false_accept_rate": sum(not row["low_confidence"] for row in no_answer) / len(no_answer) if no_answer else None,
        "false_reject_rate": sum(row["low_confidence"] for row in answerable_gated) / len(answerable_gated) if answerable_gated else None,
        "p95_latency_ms": percentile([row["latency_ms"] for row in successful], 95) if successful else None,
        "reranker_fallback_rate": sum(row["reranker_fallback"] for row in gated) / len(gated) if gated else None,
    }


async def evaluate(benchmark: LongDocumentBenchmark, *, service=None, strategy="bm25", top_k=3) -> dict:
    bm25 = InMemoryBM25Retriever()
    bm25.build(benchmark.documents)
    rows = []
    for case in benchmark.cases:
        started = time.perf_counter()
        try:
            if service is None:
                documents = await bm25.search(case.query, top_k=top_k)
                low_confidence, fallback, reasons = None, False, []
            else:
                result = await service.retrieve(case.query, strategy=strategy, top_k=top_k)
                documents = result.documents
                low_confidence = result.low_confidence
                fallback = result.diagnostics.reranker_fallback
                reasons = result.confidence_reasons
        except VectorRetrievalError:
            # Keep failures visible and redact provider/DSN details. Never score an
            # operational error as a correct refusal on an unanswerable question.
            rows.append({"id": case.case_id, "split": case.split, "error_type": "VectorRetrievalError"})
            continue
        predicted = [doc.document_id for doc in documents]
        rows.append({
            "id": case.case_id, "split": case.split, "query": case.query, "tags": list(case.tags),
            "answerable": bool(case.evidence), "retrieved_document_ids": predicted,
            "retrieved_source_ids": [benchmark.fragments[doc_id].source_id for doc_id in predicted],
            "raw": score_case(case, predicted, benchmark.fragments, k=top_k),
            "accepted": score_case(case, [] if low_confidence else predicted, benchmark.fragments, k=top_k),
            "low_confidence": low_confidence, "confidence_reasons": reasons,
            "reranker_fallback": fallback,
            "top1_vector_score": documents[0].vector_score if documents else None,
            "latency_ms": (time.perf_counter() - started) * 1000,
        })
    return {
        **preview(benchmark), "strategy": strategy, "top_k": top_k,
        "metric_semantics": "K counts returned slots, source repeats retain ranks; evidence requires full span containment; MRR truncated at K",
        "raw_metrics": summarize(rows),
        "accepted_metrics": summarize(rows, accepted=True) if service is not None else None,
        "splits": {split: {"raw": summarize([row for row in rows if row["split"] == split]),
                           "accepted": summarize([row for row in rows if row["split"] == split], accepted=True) if service is not None else None}
                   for split in ("tuning", "validation", "test")},
        "failures": [row["id"] for row in rows if "error_type" in row or
                     (row["answerable"] and row["raw"]["evidence_recall_at_k"] < 1)],
        "case_results": rows,
    }


async def execute_live(benchmark: LongDocumentBenchmark, *, action: str, strategy: str, threshold: float, top_k: int) -> dict:
    from openai import AsyncOpenAI

    if action not in {"import", "evaluate"}:
        raise ValueError("live action must be import or evaluate")
    # Never silently fall back to the application's DATABASE_URL.
    required = ("LONG_DOCUMENT_EVAL_DATABASE_URL", "DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL")
    if any(not os.environ.get(name) for name in required):
        raise ValueError("live mode requires LONG_DOCUMENT_EVAL_DATABASE_URL and server-side provider configuration")
    if os.environ.get("QWEN_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL) != DEFAULT_EMBEDDING_MODEL:
        raise ValueError("embedding model must match the current retrieval contract")
    if os.environ.get("EMBEDDING_DIMENSIONS", "1536") != "1536":
        raise ValueError("embedding dimensions must be 1536")
    policy = RetrievalConfidencePolicy(min_top1_vector_score=threshold)
    pool = await create_pool(dsn=os.environ["LONG_DOCUMENT_EVAL_DATABASE_URL"], min_size=1, max_size=2)
    try:
        async with pool.acquire() as connection:
            if not await connection.fetchval("SELECT to_regclass('public.knowledge_chunk_provenance')"):
                raise ValueError("apply migrations 001 and 003 to the isolated evaluation database first")
            stored_sources = await connection.fetch("SELECT * FROM knowledge_sources")
            stored_fragments = await connection.fetch(
                "SELECT chunk_id, source_id, start_offset, end_offset FROM knowledge_chunk_provenance"
            )
        actual = await load_knowledge_documents(pool)
        expected_sources = {source["source_id"]: source for source, _ in benchmark.imports}
        for record in stored_sources:
            expected = expected_sources.get(record["source_id"])
            if expected is None or any(record[key] != value for key, value in expected.items()):
                raise ValueError("database source metadata differs from this corpus variant")
        for record in stored_fragments:
            expected_fragment = benchmark.fragments.get(str(record["chunk_id"]))
            if expected_fragment is None or (
                record["source_id"], record["start_offset"], record["end_offset"]
            ) != (expected_fragment.source_id, expected_fragment.start, expected_fragment.end):
                raise ValueError("database provenance differs from labelled source offsets")
        if {str(record["chunk_id"]) for record in stored_fragments} != {doc.document_id for doc in actual}:
            raise ValueError("database has missing provenance or unrelated documents")
        if action == "import":
            # Fresh DB or an exact subset from an interrupted prior import only.
            expected_docs = {doc.document_id: doc for doc in benchmark.documents}
            if any(doc.document_id not in expected_docs or doc.content != expected_docs[doc.document_id].content
                   or doc.title != expected_docs[doc.document_id].title
                   or doc.category != expected_docs[doc.document_id].category for doc in actual):
                raise ValueError("refusing to import into an unrelated or different-variant knowledge base")
        else:
            benchmark.validate_corpus(actual)
            if len(stored_sources) != len(expected_sources):
                raise ValueError("database is missing labelled source metadata")
        async with AsyncOpenAI(api_key=os.environ["DASHSCOPE_API_KEY"], base_url=os.environ["DASHSCOPE_BASE_URL"],
                               max_retries=0, timeout=30) as client:
            if action == "import":
                inserted = 0
                for source, rows in benchmark.imports:
                    # Source transaction is atomic; a corpus import is resumable,
                    # not one transaction spanning all external provider calls.
                    inserted += await insert_source(pool, source, await embed_chunks(client, source, rows))
                benchmark.validate_corpus(await load_knowledge_documents(pool))
                return {**preview(benchmark), "inserted_source_count": inserted}
            bm25 = InMemoryBM25Retriever()
            bm25.build(actual)
            rerank_model = os.environ.get("QWEN_RERANK_MODEL", "qwen-plus")
            service = HybridRetrievalService(
                vector_retriever=PgVectorRetriever(model_client=client, db_pool=pool),
                bm25_retriever=bm25, fusion_strategy=ReciprocalRankFusion(),
                reranker=LLMReranker(model_client=client, model=rerank_model), confidence_policy=policy,
            )
            report = await evaluate(benchmark, service=service, strategy=strategy, top_k=top_k)
            report["configuration"] = {"embedding_model": DEFAULT_EMBEDDING_MODEL,
                                       "dimensions": EMBEDDING_DIMENSIONS, "rerank_model": rerank_model,
                                       "min_top1_vector_score": threshold, "cache": "disabled",
                                       "candidate_top_k": 10, "concurrency": 1}
            return report
    finally:
        await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--action", choices=("preview", "bm25", "import", "evaluate"), default="preview")
    parser.add_argument("--variant", choices=("whole", "chunked"), default="chunked")
    parser.add_argument("--chunk-size", type=int, default=1200)
    parser.add_argument("--overlap", type=int, default=150)
    parser.add_argument("--top-k", type=int, choices=range(1, 101), default=3)
    parser.add_argument("--strategy", choices=("vector_only", "hybrid", "hybrid_rerank"), default="hybrid_rerank")
    parser.add_argument("--threshold", type=float, default=DEFAULT_MIN_TOP1_VECTOR_SCORE)
    parser.add_argument("--execute-live", action="store_true", help="authorize provider calls; import also writes to the explicitly configured isolated DB")
    parser.add_argument("--output", type=Path, help="optional local report; do not commit reports")
    args = parser.parse_args()
    if args.action in {"import", "evaluate"} and not args.execute_live:
        parser.error("live action requires --execute-live; preview and bm25 are offline")
    benchmark = load_benchmark(args.manifest, args.dataset, variant=args.variant,
                               chunk_size=args.chunk_size, overlap=args.overlap)
    if args.action == "preview":
        report = preview(benchmark)
    elif args.action == "bm25":
        report = asyncio.run(evaluate(benchmark, top_k=args.top_k))
    else:
        from dotenv import load_dotenv
        load_dotenv()
        report = asyncio.run(execute_live(benchmark, action=args.action, strategy=args.strategy,
                                          threshold=args.threshold, top_k=args.top_k))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
