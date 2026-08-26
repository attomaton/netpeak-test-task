"""Tests for cache, checkpoint, review queue and fallback behavior."""

import asyncio
import json

from src.async_processing import classify_requests_async
from src.cache import ClassificationCache
from src.checkpoint import CheckpointStore
from src.models import ClassificationResult, InputRequest, RequestResult
from src.monitoring import MetricsCollector
from src.providers import FallbackLLMClient
from src.rate_limit import QuotaAwareRateLimiter
from src.review import build_review_queue


def request(id_: str, text: str = "Потрібен звіт по кампаніях.") -> InputRequest:
    return InputRequest(
        id=id_,
        channel="Slack",
        timestamp="2026-06-08 10:00",
        raw_text=text,
    )


def valid_payload() -> dict:
    return {
        "category": "звіт/аналітика",
        "target_department": "маркетинг",
        "priority": "medium",
        "short_summary": "Підготувати звіт по кампаніях.",
        "requested_actions": ["Зібрати метрики"],
        "needs_clarification": False,
        "clarification_question": None,
    }


class CountingClassifier:
    def __init__(self) -> None:
        self.calls = 0

    def classify_request(self, item: InputRequest) -> RequestResult:
        self.calls += 1
        return RequestResult(
            id=item.id,
            channel=item.channel,
            timestamp=item.timestamp,
            classification=ClassificationResult.model_validate(valid_payload()),
        )


def test_cache_uses_normalized_raw_text(tmp_path) -> None:
    cache = ClassificationCache(tmp_path / "cache.json")
    cache.set("  Привіт   команда  ", ClassificationResult.model_validate(valid_payload()))
    restored = cache.get("привіт команда")
    assert restored is not None
    assert restored.category.value == "звіт/аналітика"


def test_checkpoint_resume_skips_successful_items(tmp_path) -> None:
    store = CheckpointStore(tmp_path / "checkpoint.json")
    classifier = CountingClassifier()
    requests = [request("REQ-1"), request("REQ-2")]

    first = asyncio.run(classify_requests_async(requests[:1], classifier, checkpoint=store))
    second = asyncio.run(classify_requests_async(requests, classifier, checkpoint=store))

    assert len(first) == 1
    assert [item.id for item in second] == ["REQ-1", "REQ-2"]
    assert classifier.calls == 2


def test_review_queue_contains_high_priority_and_errors(tmp_path) -> None:
    high = RequestResult(
        id="REQ-1",
        channel="Slack",
        timestamp="2026-06-08",
        classification=ClassificationResult.model_validate(
            {**valid_payload(), "priority": "high"}
        ),
    )
    error = RequestResult(
        id="REQ-2",
        channel="Email",
        timestamp="2026-06-08",
        error={"type": "ClientError", "message": "quota", "attempts": 1},
    )
    path = tmp_path / "review.json"
    count = build_review_queue([request("REQ-1"), request("REQ-2")], [high, error], path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert count == 2
    assert payload[0]["reasons"] == ["high_priority"]
    assert payload[1]["reasons"] == ["processing_error"]


def test_fallback_client_uses_second_provider() -> None:
    calls = []

    class Failing:
        def classify(self, raw_text: str):
            calls.append("primary")
            raise RuntimeError("offline")

    class Working:
        def classify(self, raw_text: str):
            calls.append("fallback")
            return valid_payload()

    result = FallbackLLMClient([Failing(), Working()]).classify("текст")
    assert result["category"] == "звіт/аналітика"
    assert calls == ["primary", "fallback"]


def test_monitoring_tracks_results() -> None:
    metrics = MetricsCollector()
    result = RequestResult(
        id="REQ-1",
        channel="Slack",
        timestamp="2026-06-08",
        classification=ClassificationResult.model_validate(valid_payload()),
    )
    metrics.record_attempt()
    metrics.record_result(result, 0.25)
    snapshot = metrics.snapshot(1)
    assert snapshot["successful"] == 1
    assert snapshot["llm_attempts"] == 1
def test_quota_rate_limiter_waits_for_window() -> None:
    now = [0.0]
    sleeps = []

    def clock() -> float:
        return now[0]

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    limiter = QuotaAwareRateLimiter(
        requests_per_window=1,
        window_seconds=10.0,
        sleep=sleep,
        clock=clock,
    )
    limiter.acquire()
    limiter.acquire()
    assert sleeps == [10.0]
