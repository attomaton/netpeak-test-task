"""Dependency-free run metrics and structured monitoring output."""

from __future__ import annotations

import json
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any

from .models import RequestResult


class MetricsCollector:
    """Collect operational metrics without storing raw request text or secrets."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.started_at = time.time()
        self._attempts = 0
        self._retries = 0
        self._cache_hits = 0
        self._fallback_uses = 0
        self._successful = 0
        self._errors = 0
        self._durations: list[float] = []
        self._error_types: Counter[str] = Counter()

    def record_attempt(self, retry: bool = False) -> None:
        with self._lock:
            self._attempts += 1
            if retry:
                self._retries += 1

    def record_cache_hit(self) -> None:
        with self._lock:
            self._cache_hits += 1

    def record_fallback(self) -> None:
        with self._lock:
            self._fallback_uses += 1

    def record_result(self, result: RequestResult, duration_seconds: float) -> None:
        with self._lock:
            self._durations.append(max(duration_seconds, 0.0))
            if result.classification is not None:
                self._successful += 1
            else:
                self._errors += 1
                if result.error is not None:
                    self._error_types[result.error.type] += 1

    def snapshot(self, total_requests: int | None = None) -> dict[str, Any]:
        with self._lock:
            durations = sorted(self._durations)
            elapsed = max(time.time() - self.started_at, 0.0)
            return {
                "total_requests": total_requests if total_requests is not None else len(durations),
                "successful": self._successful,
                "errors": self._errors,
                "cache_hits": self._cache_hits,
                "llm_attempts": self._attempts,
                "retries": self._retries,
                "fallback_uses": self._fallback_uses,
                "elapsed_seconds": round(elapsed, 3),
                "average_request_seconds": round(sum(durations) / len(durations), 3)
                if durations
                else 0.0,
                "p95_request_seconds": round(_percentile(durations, 0.95), 3)
                if durations
                else 0.0,
                "error_types": dict(self._error_types),
            }

    def write(self, path: Path, total_requests: int | None = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.snapshot(total_requests), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    index = min(len(values) - 1, max(0, int((len(values) - 1) * percentile)))
    return values[index]

