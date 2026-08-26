from pathlib import Path

import pytest

from evals.dataset import load_retrieval_dataset


def test_v1_dataset_has_30_unique_cases():
    cases = load_retrieval_dataset(Path("evals/datasets/retrieval_v1.jsonl"))
    assert len(cases) == 30
    assert len({case.case_id for case in cases}) == 30
    assert any(not case.relevant_document_titles for case in cases)


def test_duplicate_ids_are_rejected(tmp_path):
    path = tmp_path / "data.jsonl"
    path.write_text(
        '{"id":"x","query":"q","relevant_document_titles":[]}\n'
        '{"id":"x","query":"q2","relevant_document_titles":[]}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate eval id"):
        load_retrieval_dataset(path)
