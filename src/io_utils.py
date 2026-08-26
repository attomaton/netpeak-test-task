"""CSV input and JSON output helpers."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .models import InputRequest, RequestResult

REQUIRED_COLUMNS = {"id", "channel", "timestamp", "raw_text"}


def load_requests(path: Path) -> list[InputRequest]:
    """Load and validate all required CSV columns without mutating the source."""

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        columns = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise ValueError(f"CSV is missing required columns: {', '.join(sorted(missing))}")
        return [InputRequest.model_validate(row) for row in reader]


def write_output(path: Path, results: list[RequestResult]) -> None:
    """Write readable UTF-8 JSON with Ukrainian text preserved."""

    payload = [result.model_dump(mode="json") for result in results]
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

