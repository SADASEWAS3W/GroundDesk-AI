"""Run the three retrieval strategies against the labelled dataset."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI

from agent.retrieval import (
    HybridRetrievalService,
    InMemoryBM25Retriever,
    LLMReranker,
    PgVectorRetriever,
    ReciprocalRankFusion,
    load_knowledge_documents,
)
from database.pool import create_pool
from evals.dataset import load_retrieval_dataset
from evals.metrics import percentile, summarize_predictions

STRATEGIES = ("vector_only", "hybrid", "hybrid_rerank")


async def run_live(
    dataset_path: Path,
    *,
    strategies: tuple[str, ...] = STRATEGIES,
) -> dict:
    required = ("DATABASE_URL", "DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"missing live evaluation configuration: {', '.join(missing)}")

    cases = load_retrieval_dataset(dataset_path)
    pool = await create_pool(dsn=os.environ["DATABASE_URL"], min_size=1, max_size=5)
    client = AsyncOpenAI(
        api_key=os.environ["DASHSCOPE_API_KEY"],
        base_url=os.environ["DASHSCOPE_BASE_URL"],
    )
    try:
        corpus = await load_knowledge_documents(pool)
        title_to_id: dict[str, str] = {}
        for document in corpus:
            if document.title in title_to_id:
                raise RuntimeError(f"knowledge title is not unique: {document.title}")
            title_to_id[document.title] = document.document_id
        unknown_titles = sorted({
            title
            for case in cases
            for title in case.relevant_document_titles
            if title not in title_to_id
        })
        if unknown_titles:
            raise RuntimeError(f"dataset titles missing from knowledge base: {unknown_titles}")

        bm25 = InMemoryBM25Retriever()
        bm25.build(corpus)
        service = HybridRetrievalService(
            vector_retriever=PgVectorRetriever(model_client=client, db_pool=pool),
            bm25_retriever=bm25,
            fusion_strategy=ReciprocalRankFusion(),
            reranker=LLMReranker(
                model_client=client,
                model=os.environ.get("QWEN_RERANK_MODEL", "qwen-plus"),
            ),
        )

        strategy_reports = {}
        for strategy in strategies:
            metric_inputs = []
            split_metric_inputs = {"tuning": [], "validation": []}
            latencies = []
            failures = []
            case_results = []
            fallback_count = 0
            low_confidence_count = 0
            answerable_low_confidence_count = 0
            for case in cases:
                started = time.perf_counter()
                result = await service.retrieve(case.query, strategy=strategy, top_k=3)
                latency_ms = (time.perf_counter() - started) * 1000
                retrieved = [document.document_id for document in result.documents]
                relevant = {
                    title_to_id[title] for title in case.relevant_document_titles
                }
                accepted = [] if result.low_confidence else retrieved
                metric_prediction = retrieved if relevant else accepted
                metric_inputs.append((relevant, metric_prediction))
                split_metric_inputs[case.split].append((relevant, metric_prediction))
                latencies.append(latency_ms)
                fallback_count += int(result.diagnostics.reranker_fallback)
                low_confidence_count += int(result.low_confidence)
                answerable_low_confidence_count += int(
                    bool(relevant) and result.low_confidence
                )
                case_results.append({
                    "id": case.case_id,
                    "query": case.query,
                    "answerable": bool(relevant),
                    "split": case.split,
                    "retrieved_document_ids": retrieved,
                    "accepted_document_ids": accepted,
                    "predicted_titles": [document.title for document in result.documents],
                    "documents": [
                        {
                            "document_id": document.document_id,
                            "title": document.title,
                            "source_retrievers": list(document.source_retrievers),
                            "vector_score": document.vector_score,
                            "bm25_score": document.bm25_score,
                            "rrf_score": document.rrf_score,
                            "rerank_score": document.rerank_score,
                        }
                        for document in result.documents
                    ],
                    "low_confidence": result.low_confidence,
                    "confidence_reasons": list(result.confidence_reasons),
                    "reranker_fallback": result.diagnostics.reranker_fallback,
                    "fallback_reason": result.diagnostics.fallback_reason,
                    "latency_ms": latency_ms,
                    "tags": list(case.tags),
                })
                if relevant and not relevant.intersection(retrieved[:3]):
                    failures.append({
                        "id": case.case_id,
                        "query": case.query,
                        "relevant_document_ids": sorted(relevant),
                        "predicted_document_ids": retrieved,
                        "predicted_titles": [document.title for document in result.documents],
                        "tags": list(case.tags),
                    })
            summary = asdict(summarize_predictions(metric_inputs, k=3))
            summary.update({
                "splits": {
                    split: asdict(summarize_predictions(items, k=3))
                    for split, items in split_metric_inputs.items()
                },
                "p50_latency_ms": percentile(latencies, 50),
                "p95_latency_ms": percentile(latencies, 95),
                "reranker_fallback_count": fallback_count,
                "low_confidence_count": low_confidence_count,
                "answerable_low_confidence_count": answerable_low_confidence_count,
                "failures": failures,
                "case_results": case_results,
            })
            strategy_reports[strategy] = summary
        return {
            "dataset": str(dataset_path),
            "case_count": len(cases),
            "strategies": strategy_reports,
            "label_resolution": "relevant_document_titles resolved to current database UUIDs",
        }
    finally:
        await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("evals/datasets/retrieval_v1.jsonl"),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--execute-live",
        action="store_true",
        help="authorize real embedding and reranker API calls",
    )
    parser.add_argument(
        "--strategies",
        nargs="+",
        choices=STRATEGIES,
        default=list(STRATEGIES),
        help="strategies to evaluate (default: all)",
    )
    args = parser.parse_args()
    if not args.execute_live:
        raise SystemExit(
            "Live evaluation is disabled. Pass --execute-live to authorize provider calls."
        )
    load_dotenv()
    report = asyncio.run(run_live(args.dataset, strategies=tuple(args.strategies)))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
