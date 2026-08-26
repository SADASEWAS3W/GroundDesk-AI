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


async def run_live(dataset_path: Path) -> dict:
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
        for strategy in STRATEGIES:
            metric_inputs = []
            latencies = []
            failures = []
            fallback_count = 0
            for case in cases:
                started = time.perf_counter()
                result = await service.retrieve(case.query, strategy=strategy, top_k=3)
                latency_ms = (time.perf_counter() - started) * 1000
                predicted = [document.document_id for document in result.documents]
                relevant = {
                    title_to_id[title] for title in case.relevant_document_titles
                }
                metric_inputs.append((relevant, predicted))
                latencies.append(latency_ms)
                fallback_count += int(result.diagnostics.reranker_fallback)
                if relevant and not relevant.intersection(predicted[:3]):
                    failures.append({
                        "id": case.case_id,
                        "query": case.query,
                        "relevant_document_ids": sorted(relevant),
                        "predicted_document_ids": predicted,
                        "predicted_titles": [document.title for document in result.documents],
                        "tags": list(case.tags),
                    })
            summary = asdict(summarize_predictions(metric_inputs, k=3))
            summary.update({
                "p50_latency_ms": percentile(latencies, 50),
                "p95_latency_ms": percentile(latencies, 95),
                "reranker_fallback_count": fallback_count,
                "failures": failures,
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
    args = parser.parse_args()
    if not args.execute_live:
        raise SystemExit(
            "Live evaluation is disabled. Pass --execute-live to authorize provider calls."
        )
    load_dotenv()
    report = asyncio.run(run_live(args.dataset))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
