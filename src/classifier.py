"""Classification orchestration, local validation, retry and error isolation."""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from typing import Any, Protocol

from .cache import ClassificationCache
from .models import (
    InputRequest,
    ProcessingError,
    RequestResult,
    parse_llm_output,
)
from .monitoring import MetricsCollector
from .rate_limit import QuotaAwareRateLimiter

logger = logging.getLogger(__name__)


class LLMClient(Protocol):
    def classify(self, raw_text: str) -> Any:
        """Return a raw or already-parsed model response."""


def sanitize_error_message(message: str, secret: str | None = None) -> str:
    """Avoid putting an API key into logs or output if an SDK ever echoes it."""

    safe = message.replace(secret, "[REDACTED]") if secret else message
    return safe.strip() or "unknown error"


class RequestClassifier:
    """Classify each request independently so one failure cannot stop the batch."""

    def __init__(
        self,
        llm_client: LLMClient,
        max_attempts: int = 3,
        backoff_seconds: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
        api_key: str | None = None,
        cache: ClassificationCache | None = None,
        rate_limiter: QuotaAwareRateLimiter | None = None,
        metrics: MetricsCollector | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if backoff_seconds < 0:
            raise ValueError("backoff_seconds cannot be negative")
        self.llm_client = llm_client
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self.sleep = sleep
        self.api_key = api_key
        self.cache = cache
        self.rate_limiter = rate_limiter
        self.metrics = metrics

    def classify_request(self, request: InputRequest) -> RequestResult:
        """Return a success or explicit error result after bounded retries."""

        started = time.perf_counter()
        if self.cache is not None:
            cached = self.cache.get(request.raw_text)
            if cached is not None:
                if self.metrics is not None:
                    self.metrics.record_cache_hit()
                result = RequestResult(
                    id=request.id,
                    channel=request.channel,
                    timestamp=request.timestamp,
                    classification=cached,
                )
                self._record_result(result, started)
                logger.info("Cache hit for request %s", request.id)
                return result

        for attempt in range(1, self.max_attempts + 1):
            try:
                if self.rate_limiter is not None:
                    self.rate_limiter.acquire()
                if self.metrics is not None:
                    self.metrics.record_attempt(retry=attempt > 1)
                raw_output = self.llm_client.classify(request.raw_text)
                classification = parse_llm_output(raw_output)
                if self.cache is not None:
                    try:
                        self.cache.set(request.raw_text, classification)
                    except OSError as exc:
                        logger.warning("Could not write classification cache: %s", exc)
                logger.info("Classified request %s on attempt %s", request.id, attempt)
                result = RequestResult(
                    id=request.id,
                    channel=request.channel,
                    timestamp=request.timestamp,
                    classification=classification,
                )
                self._record_result(result, started)
                return result
            except Exception as exc:  # API, timeout, JSON and Pydantic errors are all retryable here.
                error_type = type(exc).__name__
                message = sanitize_error_message(str(exc), self.api_key)
                quota_delay = _extract_retry_delay(message)
                if quota_delay and self.rate_limiter is not None:
                    self.rate_limiter.cooldown(quota_delay)
                if attempt == self.max_attempts:
                    logger.error(
                        "Request %s failed after %s attempts: %s: %s",
                        request.id,
                        attempt,
                        error_type,
                        message,
                    )
                    result = RequestResult(
                        id=request.id,
                        channel=request.channel,
                        timestamp=request.timestamp,
                        error=ProcessingError(
                            type=error_type,
                            message=message,
                            attempts=attempt,
                        ),
                    )
                    self._record_result(result, started)
                    return result

                delay = self.backoff_seconds * (2 ** (attempt - 1))
                if quota_delay is not None:
                    delay = max(delay, quota_delay)
                logger.warning(
                    "Retrying request %s after attempt %s/%s in %.2fs: %s: %s",
                    request.id,
                    attempt,
                    self.max_attempts,
                    delay,
                    error_type,
                    message,
                )
                self.sleep(delay)

        raise AssertionError("unreachable")

    def _record_result(self, result: RequestResult, started: float) -> None:
        if self.metrics is not None:
            self.metrics.record_result(result, time.perf_counter() - started)


def classify_requests(
    requests: list[InputRequest],
    classifier: RequestClassifier,
) -> list[RequestResult]:
    """Classify a batch while preserving input order."""

    results: list[RequestResult] = []
    for index, request in enumerate(requests, start=1):
        logger.info("Processing request %s/%s: %s", index, len(requests), request.id)
        results.append(classifier.classify_request(request))
    return results


def _is_json_error(exc: Exception) -> bool:
    """Kept as a named helper to make error categories easy to extend later."""

    return isinstance(exc, (json.JSONDecodeError, ValueError, TypeError))


def _extract_retry_delay(message: str) -> float | None:
    """Read common Gemini RetryInfo/English retry hints from an error message."""

    matches = re.findall(
        r"(?:retry in|retryDelay[^0-9]*)([0-9]+(?:\.[0-9]+)?)\s*s", message
    )
    return max((float(value) for value in matches), default=0.0) or None
