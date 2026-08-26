"""Human-review queue for ambiguous, urgent and failed requests."""

from __future__ import annotations

import json
from pathlib import Path

from .models import InputRequest, RequestResult


def review_reasons(result: RequestResult) -> list[str]:
    """Return deterministic reasons why an item should be checked by a person."""

    reasons: list[str] = []
    if result.error is not None:
        reasons.append("processing_error")
        return reasons
    classification = result.classification
    assert classification is not None
    if classification.needs_clarification:
        reasons.append("needs_clarification")
    if classification.priority.value == "high":
        reasons.append("high_priority")
    if classification.category.value == "поза скоупом":
        reasons.append("out_of_scope_or_uncertain")
    return reasons


def build_review_queue(
    requests: list[InputRequest],
    results: list[RequestResult],
    path: Path,
) -> int:
    """Write pending review records and return their count.

    The queue is non-blocking: the batch completes, and a person can review the
    generated JSON afterwards. Raw text is included because it is required for
    a useful human decision; the file is ignored by Git by default.
    """

    by_id = {request.id: request for request in requests}
    items: list[dict] = []
    for result in results:
        reasons = review_reasons(result)
        if not reasons:
            continue
        request = by_id.get(result.id)
        if request is None:
            continue
        items.append(
            {
                "id": request.id,
                "status": "pending",
                "reasons": reasons,
                "request": {
                    "channel": request.channel,
                    "timestamp": request.timestamp,
                    "raw_text": request.raw_text,
                },
                "classification": result.classification.model_dump(mode="json")
                if result.classification is not None
                else None,
                "error": result.error.model_dump(mode="json")
                if result.error is not None
                else None,
                "reviewer_notes": None,
            }
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(items)

