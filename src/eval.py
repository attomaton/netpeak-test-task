"""Offline evaluation metrics for the labeled request dataset."""

from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EvalCase:
    """One manually labeled evaluation example."""

    id: str
    raw_text: str
    category: str
    priority: str
    needs_clarification: bool


def load_labeled_dataset(path: Path) -> list[EvalCase]:
    """Load a CSV with ground-truth labels and reject malformed rows."""

    required = {
        "id",
        "raw_text",
        "category",
        "priority",
        "needs_clarification",
    }
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Eval CSV is missing columns: {', '.join(sorted(missing))}")
        cases: list[EvalCase] = []
        seen: set[str] = set()
        for row in reader:
            identifier = (row.get("id") or "").strip()
            if not identifier or identifier in seen:
                raise ValueError(f"Eval dataset contains an empty or duplicate id: {identifier!r}")
            seen.add(identifier)
            cases.append(
                EvalCase(
                    id=identifier,
                    raw_text=(row.get("raw_text") or "").strip(),
                    category=(row.get("category") or "").strip(),
                    priority=(row.get("priority") or "").strip(),
                    needs_clarification=_parse_bool(row.get("needs_clarification", "")),
                )
            )
        return cases


def load_predictions(path: Path) -> dict[str, dict[str, Any]]:
    """Load output.json and return successful classifications by request id."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Predictions JSON must contain an array.")
    predictions: dict[str, dict[str, Any]] = {}
    for item in payload:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError("Each prediction must contain a string id.")
        classification = item.get("classification")
        if isinstance(classification, dict):
            predictions[item["id"]] = classification
    return predictions


def calculate_metrics(
    y_true: Sequence[Hashable],
    y_pred: Sequence[Hashable],
) -> dict[str, Any]:
    """Calculate macro precision, recall and F1 without a heavy ML dependency."""

    if len(y_true) != len(y_pred):
        raise ValueError("y_true and y_pred must have the same length.")
    labels = list(dict.fromkeys([*y_true, *y_pred]))
    per_label: dict[str, dict[str, float | int]] = {}
    for label in labels:
        true_positive = sum(actual == label and predicted == label for actual, predicted in zip(y_true, y_pred))
        false_positive = sum(actual != label and predicted == label for actual, predicted in zip(y_true, y_pred))
        false_negative = sum(actual == label and predicted != label for actual, predicted in zip(y_true, y_pred))
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_label[str(label)] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": sum(actual == label for actual in y_true),
        }
    macro_precision = sum(item["precision"] for item in per_label.values()) / len(labels) if labels else 0.0
    macro_recall = sum(item["recall"] for item in per_label.values()) / len(labels) if labels else 0.0
    macro_f1 = sum(item["f1"] for item in per_label.values()) / len(labels) if labels else 0.0
    accuracy = sum(actual == predicted for actual, predicted in zip(y_true, y_pred)) / len(y_true) if y_true else 0.0
    return {
        "precision": round(macro_precision, 4),
        "recall": round(macro_recall, 4),
        "f1": round(macro_f1, 4),
        "accuracy": round(accuracy, 4),
        "per_label": per_label,
    }


def evaluate_predictions(
    cases: Sequence[EvalCase],
    predictions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Match labels to predictions and calculate all required field metrics."""

    missing = [case.id for case in cases if case.id not in predictions]
    if missing:
        raise ValueError(f"Missing successful predictions for: {', '.join(missing)}")
    return {
        "dataset_size": len(cases),
        "metrics": {
            "category": calculate_metrics(
                [case.category for case in cases],
                [str(predictions[case.id].get("category")) for case in cases],
            ),
            "priority": calculate_metrics(
                [case.priority for case in cases],
                [str(predictions[case.id].get("priority")) for case in cases],
            ),
            "needs_clarification": calculate_metrics(
                [case.needs_clarification for case in cases],
                [bool(predictions[case.id].get("needs_clarification")) for case in cases],
            ),
        },
    }


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "так"}:
        return True
    if normalized in {"0", "false", "no", "ні"}:
        return False
    raise ValueError(f"Invalid boolean label: {value!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate classification output on labeled CSV.")
    parser.add_argument("--dataset", type=Path, default=Path("eval/labeled_requests.csv"))
    parser.add_argument("--predictions", type=Path, default=Path("eval/predictions.json"))
    parser.add_argument("--output", type=Path, default=Path("eval/metrics.json"))
    args = parser.parse_args()

    report = evaluate_predictions(
        load_labeled_dataset(args.dataset),
        load_predictions(args.predictions),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
