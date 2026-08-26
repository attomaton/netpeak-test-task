"""Evaluation metric tests."""

from src.eval import calculate_metrics


def test_metrics_are_calculated_for_binary_labels() -> None:
    metrics = calculate_metrics([True, True, False, False], [True, False, False, False])
    assert metrics["accuracy"] == 0.75
    assert metrics["per_label"]["True"]["precision"] == 1.0
    assert metrics["per_label"]["True"]["recall"] == 0.5
    assert metrics["per_label"]["True"]["f1"] == 0.6667
