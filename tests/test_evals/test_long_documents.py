import ast
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.retrieval.models import RetrievedDocument
from agent.retrieval.vector import VectorRetrievalError
from evals import long_document_eval as runner
from evals.long_document_labels import (
    DEFAULT_DATASET, DEFAULT_MANIFEST, Evidence, LongDocumentCase, contains,
    load_benchmark, score_case,
)


def test_long_corpus_covers_all_seed_articles_and_actual_late_evidence():
    benchmark = load_benchmark()
    tree = ast.parse(Path("database/migrations/002_seed_knowledge_base.py").read_text(encoding="utf-8"))
    articles = next(ast.literal_eval(node.value) for node in tree.body
                    if isinstance(node, ast.AnnAssign) and node.target.id == "ARTICLES")
    titles = [title for source in benchmark.sources.values() for title in source["seed_titles"]]
    assert len(titles) == len(set(titles)) == len(articles) == 18
    assert set(titles) == {article["title"] for article in articles}
    assert len(benchmark.sources) == 6
    assert all(len(source["content"]) > 4000 for source in benchmark.sources.values())
    assert all(len(rows) >= 4 for _, rows in benchmark.imports)
    assert len(benchmark.cases) == 36
    assert sum(not case.evidence for case in benchmark.cases) == 6
    assert sum(len({label.source_id for label in case.evidence}) > 1 for case in benchmark.cases) == 6
    assert all(sum(case.split == split for case in benchmark.cases) == 12
               for split in ("tuning", "validation", "test"))
    for case in benchmark.cases:
        if "late-evidence" in case.tags:
            assert any(label.start > 2000 for label in case.evidence), case.case_id
    assert runner.preview(benchmark)["uncoverable_evidence"] == []


def test_variants_share_sources_queries_fingerprint_but_not_document_ids():
    whole, chunked = load_benchmark(variant="whole"), load_benchmark()
    assert len(whole.documents) == 6
    assert whole.fingerprint == chunked.fingerprint
    assert whole.sources == chunked.sources and whole.cases == chunked.cases
    assert set(whole.fragments).isdisjoint(chunked.fragments)
    for source, rows in whole.imports:
        assert len(rows) == 1
        assert rows[0]["content"] == whole.sources[source["source_id"]]["content"]
    assert load_benchmark(chunk_size=800, overlap=100).fingerprint == whole.fingerprint


def test_corpus_validation_rejects_wrong_variant_or_edited_content():
    benchmark = load_benchmark()
    benchmark.validate_corpus(benchmark.documents)
    with pytest.raises(ValueError, match="exactly"):
        benchmark.validate_corpus(load_benchmark(variant="whole").documents)
    edited = [replace(benchmark.documents[0], content="changed"), *benchmark.documents[1:]]
    with pytest.raises(ValueError, match="content differs"):
        benchmark.validate_corpus(edited)


def make_case(*evidence):
    return LongDocumentCase("case", "query", "tuning", "group", (), tuple(evidence))


def test_source_recall_deduplicates_hits_but_does_not_compress_ranks_or_slots():
    case = make_case(Evidence("A", 10, 20), Evidence("B", 10, 20))
    fragments = {"a1": Evidence("A", 0, 30), "a2": Evidence("A", 0, 40),
                 "a3": Evidence("A", 0, 50), "b": Evidence("B", 0, 30)}
    scores = score_case(case, ["a1", "a2", "a3", "b"], fragments, k=3)
    assert scores["source_recall_at_k"] == .5
    assert scores["source_mrr"] == 1
    assert scores["evidence_recall_at_k"] == .5
    assert scores["all_evidence_covered_at_k"] == 0
    case_b = make_case(Evidence("B", 10, 20))
    assert score_case(case_b, ["a1", "a2", "b"], fragments)["source_mrr"] == 1 / 3


def test_same_source_irrelevant_fragment_is_not_answer_evidence():
    case = make_case(Evidence("A", 100, 120))
    fragments = {"wrong": Evidence("A", 0, 50), "right": Evidence("A", 80, 130)}
    scores = score_case(case, ["wrong"], fragments)
    assert scores["source_recall_at_k"] == 1
    assert scores["evidence_recall_at_k"] == scores["evidence_mrr"] == 0


def test_overlap_does_not_inflate_evidence_denominator_and_partial_span_is_not_full_hit():
    case = make_case(Evidence("A", 10, 20), Evidence("A", 50, 60))
    fragments = {"a": Evidence("A", 0, 25), "duplicate": Evidence("A", 5, 30),
                 "partial": Evidence("A", 40, 59)}
    scores = score_case(case, ["a", "duplicate", "partial"], fragments)
    assert scores["evidence_recall_at_k"] == .5
    assert scores["chunk_recall_at_k"] == 1
    assert score_case(make_case(Evidence("A", 50, 60)), ["partial"], fragments)["evidence_mrr"] == 0


def test_no_answer_not_in_recall_denominator_and_empty_answerable_returns_zero():
    assert all(value is None for value in score_case(make_case(), [], {}).values())
    scores = score_case(make_case(Evidence("A", 0, 2)), [], {"a": Evidence("A", 0, 5)})
    assert all(value == 0 for value in scores.values())


@pytest.mark.parametrize("predicted,k", [(["unknown"], 3), (["a", "a"], 3), ([], 0)])
def test_invalid_predictions_and_k(predicted, k):
    with pytest.raises(ValueError):
        score_case(make_case(Evidence("A", 0, 2)), predicted, {"a": Evidence("A", 0, 5)}, k=k)


def write_fixture(tmp_path, *, mutate_case=None, mutate_manifest=None):
    manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    for source in manifest["sources"]:
        (tmp_path / source["path"]).write_text(
            (DEFAULT_MANIFEST.parent / source["path"]).read_text(encoding="utf-8"), encoding="utf-8")
    cases = [json.loads(line) for line in DEFAULT_DATASET.read_text(encoding="utf-8").splitlines()]
    if mutate_case:
        mutate_case(cases)
    if mutate_manifest:
        mutate_manifest(manifest)
    manifest_path, dataset_path = tmp_path / "manifest.json", tmp_path / "cases.jsonl"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    dataset_path.write_text("\n".join(json.dumps(case) for case in cases), encoding="utf-8")
    return manifest_path, dataset_path


@pytest.mark.parametrize("mutation,message", [
    (lambda cases: cases[0]["evidence"][0].update(quote="nonexistent quote"), "exactly once"),
    (lambda cases: cases[0]["evidence"][0].update(source_id="unknown"), "unknown source"),
    (lambda cases: cases[0].update(split="test"), "leak"),
    (lambda cases: cases[8].update(group_id=cases[0]["group_id"]), "group leaks"),
    (lambda cases: cases[1].update(id=cases[0]["id"]), "duplicate"),
    (lambda cases: cases[1].update(query=cases[0]["query"]), "duplicate"),
    (lambda cases: cases[0].update(evidence=[]), "no-answer tag"),
    (lambda cases: cases[0].update(evidence="bad"), "evidence must"),
    (lambda cases: cases[0]["evidence"].append(cases[0]["evidence"][0]), "duplicate evidence"),
])
def test_invalid_labels_are_rejected(tmp_path, mutation, message):
    with pytest.raises(ValueError, match=message):
        load_benchmark(*write_fixture(tmp_path, mutate_case=mutation))


def test_corpus_path_cannot_escape_manifest_directory(tmp_path):
    with pytest.raises(ValueError, match="within corpus"):
        load_benchmark(*write_fixture(tmp_path, mutate_manifest=lambda m: m["sources"][0].update(path="../outside.md")))


async def test_offline_bm25_runs_without_database_or_provider(monkeypatch):
    monkeypatch.setattr(runner, "create_pool", AsyncMock(side_effect=AssertionError("no DB")))
    for variant in ("whole", "chunked"):
        report = await runner.evaluate(load_benchmark(variant=variant))
        assert len(report["case_results"]) == 36
        assert report["strategy"] == "bm25"
        assert report["accepted_metrics"] is None
        assert report["raw_metrics"]["no_answer_precision"] is None
        assert 0 <= report["raw_metrics"]["source_recall_at_k"] <= 1
        assert 0 <= report["raw_metrics"]["evidence_mrr"] <= 1


async def test_live_result_scoring_refusal_and_provider_error_are_separate():
    benchmark = load_benchmark()
    service = MagicMock()
    lookup = {case.query: case for case in benchmark.cases}
    async def retrieve(query, **kwargs):
        case = lookup[query]
        if case.case_id == "long-001":
            raise VectorRetrievalError("private provider detail must not reach report")
        docs = [doc for doc in benchmark.documents
                if any(contains(benchmark.fragments[doc.document_id], label) for label in case.evidence)][:3]
        return SimpleNamespace(documents=docs, low_confidence=not case.evidence,
                               diagnostics=SimpleNamespace(reranker_fallback=False), confidence_reasons=[])
    service.retrieve = retrieve
    report = await runner.evaluate(benchmark, service=service, strategy="hybrid_rerank")
    metrics = report["accepted_metrics"]
    assert metrics["operational_failure_count"] == 1
    assert metrics["successful_cases"] == 35
    assert metrics["no_answer_precision"] == metrics["no_answer_recall"] == 1
    assert metrics["false_accept_rate"] == metrics["false_reject_rate"] == 0
    assert "private provider detail" not in json.dumps(report)


async def test_live_requires_explicit_isolated_database(monkeypatch):
    monkeypatch.delenv("LONG_DOCUMENT_EVAL_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "must-not-be-used")
    pool = AsyncMock(side_effect=AssertionError("must not connect"))
    monkeypatch.setattr(runner, "create_pool", pool)
    with pytest.raises(ValueError, match="LONG_DOCUMENT_EVAL_DATABASE_URL"):
        await runner.execute_live(load_benchmark(), action="evaluate", strategy="hybrid", threshold=.43, top_k=3)
    pool.assert_not_called()


@pytest.mark.parametrize("action", ["import", "evaluate"])
async def test_unrelated_database_rejected_before_provider_client(monkeypatch, action):
    import openai
    for name in ("LONG_DOCUMENT_EVAL_DATABASE_URL", "DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL"):
        monkeypatch.setenv(name, "test-placeholder")
    monkeypatch.delenv("QWEN_EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv("EMBEDDING_DIMENSIONS", raising=False)
    connection = SimpleNamespace(fetchval=AsyncMock(return_value="table"), fetch=AsyncMock(return_value=[]))
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=connection)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    pool.close = AsyncMock()
    monkeypatch.setattr(runner, "create_pool", AsyncMock(return_value=pool))
    monkeypatch.setattr(runner, "load_knowledge_documents", AsyncMock(return_value=[
        RetrievedDocument("unrelated", "Unrelated", "Keep this untouched")]))
    client = MagicMock(side_effect=AssertionError("must not instantiate client"))
    monkeypatch.setattr(openai, "AsyncOpenAI", client)
    with pytest.raises(ValueError, match="unrelated|exactly"):
        await runner.execute_live(load_benchmark(), action=action, strategy="hybrid", threshold=.43, top_k=3)
    client.assert_not_called()
    pool.close.assert_awaited_once()


@pytest.mark.parametrize("action", ["import", "evaluate"])
def test_cli_live_guard_runs_before_loading_any_files(monkeypatch, action):
    monkeypatch.setattr("sys.argv", ["long_document_eval", "--action", action, "--manifest", "missing.json"])
    with pytest.raises(SystemExit) as error:
        runner.main()
    assert error.value.code == 2


@pytest.mark.parametrize("action", ["import", "evaluate"])
async def test_live_happy_path_uses_verified_provenance_and_mock_provider_only(monkeypatch, action):
    import openai
    benchmark = load_benchmark()
    for name in ("LONG_DOCUMENT_EVAL_DATABASE_URL", "DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL"):
        monkeypatch.setenv(name, "test-placeholder")
    monkeypatch.delenv("QWEN_EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv("EMBEDDING_DIMENSIONS", raising=False)
    sources = [source for source, _ in benchmark.imports] if action == "evaluate" else []
    fragments = [{"chunk_id": doc_id, "source_id": fragment.source_id,
                  "start_offset": fragment.start, "end_offset": fragment.end}
                 for doc_id, fragment in benchmark.fragments.items()] if action == "evaluate" else []
    connection = SimpleNamespace(fetchval=AsyncMock(return_value="table"),
                                 fetch=AsyncMock(side_effect=[sources, fragments]))
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=connection)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    pool.close = AsyncMock()
    create_pool = AsyncMock(return_value=pool)
    monkeypatch.setattr(runner, "create_pool", create_pool)
    monkeypatch.setattr(runner, "load_knowledge_documents", AsyncMock(
        side_effect=[[], benchmark.documents] if action == "import" else [benchmark.documents]))
    client_context = MagicMock()
    client_context.__aenter__ = AsyncMock(return_value=MagicMock())
    client_context.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(openai, "AsyncOpenAI", MagicMock(return_value=client_context))
    embedding_mock = AsyncMock(side_effect=lambda client, source, rows: rows)
    insert_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(runner, "embed_chunks", embedding_mock)
    monkeypatch.setattr(runner, "insert_source", insert_mock)
    service = SimpleNamespace(retrieve=AsyncMock(return_value=SimpleNamespace(
        documents=[], low_confidence=True, confidence_reasons=["no_retrieval_results"],
        diagnostics=SimpleNamespace(reranker_fallback=False))))
    service_constructor = MagicMock(return_value=service)
    monkeypatch.setattr(runner, "HybridRetrievalService", service_constructor)
    report = await runner.execute_live(benchmark, action=action, strategy="hybrid_rerank", threshold=.43, top_k=3)
    assert create_pool.call_args.kwargs["dsn"] == "test-placeholder"
    if action == "import":
        assert report["inserted_source_count"] == 6
        assert embedding_mock.await_count == insert_mock.await_count == 6
        service_constructor.assert_not_called()
    else:
        assert report["configuration"]["min_top1_vector_score"] == .43
        assert service_constructor.call_args.kwargs["confidence_policy"].min_top1_vector_score == .43
        assert report["accepted_metrics"]["successful_cases"] == 36
        embedding_mock.assert_not_called()
        insert_mock.assert_not_called()
    pool.close.assert_awaited_once()
