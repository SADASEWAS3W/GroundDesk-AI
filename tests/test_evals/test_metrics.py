from evals.metrics import percentile, reciprocal_rank, recall_at_k, summarize_predictions


def test_recall_and_mrr_examples():
    relevant = {"a", "b"}
    predicted = ["x", "b", "a"]
    assert recall_at_k(relevant, predicted, k=3) == 1.0
    assert reciprocal_rank(relevant, predicted) == 0.5


def test_summary_separates_no_answer_cases():
    summary = summarize_predictions([
        ({"a"}, ["a"]),
        ({"b"}, ["x"]),
        (set(), []),
        (set(), ["x"]),
    ])
    assert summary.recall_at_k == 0.5
    assert summary.mrr == 0.5
    assert summary.no_answer_accuracy == 0.5


def test_nearest_rank_percentile():
    assert percentile([10, 20, 30, 40], 95) == 40
