"""Retry and per-request error isolation tests without a real LLM."""

import json

from src.classifier import RequestClassifier
from src.models import InputRequest


class SequenceClient:
    def __init__(self, responses):
        self.responses = iter(responses)

    def classify(self, raw_text: str):
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def request() -> InputRequest:
    return InputRequest(
        id="REQ-TEST",
        channel="Slack",
        timestamp="2026-06-08 10:00",
        raw_text="Потрібен звіт по кампаніях.",
    )


def valid_response() -> dict:
    return {
        "category": "звіт/аналітика",
        "target_department": "маркетинг",
        "priority": "medium",
        "short_summary": "Підготувати звіт по кампаніях.",
        "requested_actions": ["Зібрати метрики", "Показати зміни"],
        "needs_clarification": False,
        "clarification_question": None,
    }


def test_invalid_json_is_retried_then_succeeds() -> None:
    sleeps = []
    client = SequenceClient(["not-json", valid_response()])
    result = RequestClassifier(client, max_attempts=3, backoff_seconds=0.5, sleep=sleeps.append).classify_request(request())
    assert result.classification is not None
    assert result.classification.category.value == "звіт/аналітика"
    assert sleeps == [0.5]


def test_exhausted_retries_return_explicit_error() -> None:
    client = SequenceClient([json.dumps({"category": "bad"})] * 3)
    result = RequestClassifier(client, max_attempts=3, backoff_seconds=0, sleep=lambda _: None).classify_request(request())
    assert result.classification is None
    assert result.error is not None
    assert result.error.attempts == 3

