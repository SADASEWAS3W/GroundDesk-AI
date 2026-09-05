"""Replay saved retrieval candidates through an OpenAI-compatible reranker."""

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

from agent.retrieval import LLMReranker, RetrievedDocument, load_knowledge_documents
from agent.retrieval.reranker import RerankerError
from database.pool import create_pool
from evals.dataset import load_retrieval_dataset
from evals.metrics import percentile, summarize_predictions


def _restore_candidates(case_result: dict, content_by_id: dict[str, str]) -> list[RetrievedDocument]:
    restored = []
    for rank, item in enumerate(case_result["documents"], 1):
        document_id = item["document_id"]
        content = content_by_id.get(document_id)
        if content is None:
            raise ValueError(f"report document is missing from knowledge base: {document_id}")
        restored.append(RetrievedDocument(
            document_id=document_id,
            title=item["title"],
            content=content,
            source_retrievers=tuple(item.get("source_retrievers", ())),
            vector_score=item.get("vector_score"),
            bm25_score=item.get("bm25_score"),
            rrf_score=item.get("rrf_score"),
            final_rank=rank,
        ))
    return restored


async def run_replay(
    dataset_path: Path,
    source_report_path: Path,
    *,
    provider_key: str,
    base_url: str,
    model: str,
    database_url: str,
    concurrency: int = 5,
) -> dict:
    if isinstance(concurrency, bool) or not isinstance(concurrency, int) or concurrency < 1:
        raise ValueError("concurrency must be positive")
    cases = {case.case_id: case for case in load_retrieval_dataset(dataset_path)}
    source = json.loads(source_report_path.read_text(encoding="utf-8"))
    source_rows = source["strategies"]["hybrid"]["case_results"]
    if set(cases) != {row["id"] for row in source_rows}:
        raise ValueError("source report cases do not match the dataset")

    pool = await create_pool(dsn=database_url, min_size=1, max_size=5)
    try:
        corpus = await load_knowledge_documents(pool)
    finally:
        await pool.close()
    content_by_id = {document.document_id: document.content for document in corpus}
    client = AsyncOpenAI(api_key=provider_key, base_url=base_url)
    reranker = LLMReranker(model_client=client, model=model, max_candidates=20)
    semaphore = asyncio.Semaphore(concurrency)

    async def evaluate(row: dict) -> dict:
        async with semaphore:
            started = time.perf_counter()
            try:
                candidates = _restore_candidates(row, content_by_id)
                documents = await asyncio.wait_for(
                    reranker.rerank(row["query"], candidates, top_k=3),
                    timeout=30,
                )
                return {
                    "id": row["id"],
                    "query": row["query"],
                    "split": row["split"],
                    "answerable": row["answerable"],
                    "documents": [{
                        "document_id": document.document_id,
                        "title": document.title,
                        "vector_score": document.vector_score,
                        "rerank_score": document.rerank_score,
                    } for document in documents],
                    "latency_ms": (time.perf_counter() - started) * 1000,
                }
            except (RerankerError, TimeoutError, ValueError) as exc:
                return {
                    "id": row["id"],
                    "query": row["query"],
                    "split": row["split"],
                    "answerable": row["answerable"],
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "latency_ms": (time.perf_counter() - started) * 1000,
                }

    # Fail fast on account, authentication, model, or response-contract errors
    # before scheduling the full paid evaluation batch.
    first_result = await evaluate(source_rows[0])
    if "error_type" in first_result:
        raise RuntimeError(
            "reranker preflight failed: "
            f"{first_result['error_type']}: {first_result['error']}"
        )
    results = [first_result]
    results.extend(await asyncio.gather(*(evaluate(row) for row in source_rows[1:])))
    failures = [row for row in results if "error_type" in row]
    completed = [row for row in results if "error_type" not in row]
    title_to_id = {document.title: document.document_id for document in corpus}
    metric_inputs = []
    for row in completed:
        relevant = {title_to_id[title] for title in cases[row["id"]].relevant_document_titles}
        metric_inputs.append((relevant, [doc["document_id"] for doc in row["documents"]]))
    latencies = [row["latency_ms"] for row in completed]
    return {
        "dataset": str(dataset_path),
        "source_report": str(source_report_path),
        "provider": "deepseek",
        "model": model,
        "replay_scope": "saved hybrid top-3 candidates; not full production top-20",
        "case_count": len(source_rows),
        "completed_count": len(completed),
        "failure_count": len(failures),
        "raw_metrics": asdict(summarize_predictions(metric_inputs, k=3)),
        "p50_latency_ms": percentile(latencies, 50),
        "p95_latency_ms": percentile(latencies, 95),
        "case_results": completed,
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--base-url", default="https://api.deepseek.com")
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--execute-live", action="store_true")
    args = parser.parse_args()
    if not args.execute_live:
        raise SystemExit("Live reranking is disabled. Pass --execute-live to authorize it.")
    load_dotenv()
    missing = [name for name in ("DEEPSEEK_API_KEY", "DATABASE_URL") if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"missing replay configuration: {', '.join(missing)}")
    report = asyncio.run(run_replay(
        args.dataset,
        args.source_report,
        provider_key=os.environ["DEEPSEEK_API_KEY"],
        base_url=args.base_url,
        model=args.model,
        database_url=os.environ["DATABASE_URL"],
        concurrency=args.concurrency,
    ))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
