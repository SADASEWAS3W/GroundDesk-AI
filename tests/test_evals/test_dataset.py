from pathlib import Path

import pytest

from evals.dataset import load_retrieval_dataset


def test_v1_dataset_has_30_unique_cases():
    cases = load_retrieval_dataset(Path("evals/datasets/retrieval_v1.jsonl"))
    assert len(cases) == 30
    assert len({case.case_id for case in cases}) == 30
    assert any(not case.relevant_document_titles for case in cases)
    assert sum(case.split == "tuning" for case in cases) == 20
    assert sum(case.split == "validation" for case in cases) == 10


def test_v2_dataset_has_300_versioned_cases_and_three_splits():
    cases = load_retrieval_dataset(Path("evals/datasets/retrieval_v2.jsonl"))
    assert len(cases) == 300
    assert len({case.case_id for case in cases}) == 300
    assert sum(case.split == "tuning" for case in cases) == 180
    assert sum(case.split == "validation" for case in cases) == 60
    assert sum(case.split == "test" for case in cases) == 60
    assert sum(not case.relevant_document_titles for case in cases) == 60
    tags = {tag for case in cases for tag in case.tags}
    assert {"paraphrase", "hard-negative", "multi-doc", "no-answer"} <= tags


def test_duplicate_ids_are_rejected(tmp_path):
    path = tmp_path / "data.jsonl"
    path.write_text(
        '{"id":"x","query":"q","relevant_document_titles":[]}\n'
        '{"id":"x","query":"q2","relevant_document_titles":[]}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate eval id"):
        load_retrieval_dataset(path)


def test_invalid_split_is_rejected(tmp_path):
    path = tmp_path / "data.jsonl"
    path.write_text(
        '{"id":"x","query":"q","relevant_document_titles":[],"split":"holdout"}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid eval split"):
        load_retrieval_dataset(path)
