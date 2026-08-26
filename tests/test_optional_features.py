"""Tests for optional integrations using only local fakes."""

import asyncio
from types import SimpleNamespace

from src.async_processing import classify_requests_async
from src.integrations import (
    SHEET_HEADERS,
    TelegramDigestSender,
    build_telegram_digest,
    result_to_sheet_row,
    split_telegram_message,
)
from src.models import ClassificationResult, InputRequest, RequestResult


def make_request(id_: str) -> InputRequest:
    return InputRequest(
        id=id_, channel="Slack", timestamp="2026-06-08", raw_text="Запит"
    )


def make_result(id_: str) -> RequestResult:
    return RequestResult(
        id=id_,
        channel="Slack",
        timestamp="2026-06-08",
        classification=ClassificationResult(
            category="звіт/аналітика",
            target_department="аналітика",
            priority="medium",
            short_summary="Підготувати звіт.",
            requested_actions=["Зібрати дані"],
            needs_clarification=False,
            clarification_question=None,
        ),
    )


class FakeClassifier:
    def classify_request(self, request: InputRequest) -> RequestResult:
        return make_result(request.id)


def test_async_batches_preserve_input_order() -> None:
    requests = [make_request(f"REQ-{index}") for index in range(5)]
    results = asyncio.run(
        classify_requests_async(requests, FakeClassifier(), max_concurrency=2)
    )
    assert [result.id for result in results] == [request.id for request in requests]


def test_sheet_row_and_digest_are_structured() -> None:
    result = make_result("REQ-1")
    row = result_to_sheet_row(result)
    assert len(row) == len(SHEET_HEADERS)
    assert row[0] == "REQ-1"
    assert "звіт/аналітика" in build_telegram_digest([result])


def test_telegram_message_is_split_below_limit() -> None:
    chunks = split_telegram_message("рядок\n" * 20, max_length=20)
    assert chunks
    assert all(len(chunk) <= 20 for chunk in chunks)


def test_telegram_sender_uses_mock_http_client() -> None:
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    class FakeHttpClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, data):
            calls.append((url, data))
            return FakeResponse()

    sender = TelegramDigestSender(
        "token", "chat", http_client_factory=FakeHttpClient
    )
    assert sender.send([make_result("REQ-1")]) == 1
    assert calls[0][0].endswith("/sendMessage")
    assert calls[0][1]["chat_id"] == "chat"

