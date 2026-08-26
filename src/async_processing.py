"""Bounded async/batch orchestration for independent LLM requests."""

from __future__ import annotations

import asyncio
import logging

from .checkpoint import CheckpointStore
from .classifier import RequestClassifier
from .models import InputRequest, RequestResult
from .monitoring import MetricsCollector

logger = logging.getLogger(__name__)


async def classify_requests_async(
    requests: list[InputRequest],
    classifier: RequestClassifier,
    max_concurrency: int = 4,
    checkpoint: CheckpointStore | None = None,
    metrics: MetricsCollector | None = None,
) -> list[RequestResult]:
    """Process bounded batches while preserving input order and resuming safely.

    The Gemini SDK call is synchronous, so each call runs in a worker thread.
    Batches avoid creating an unbounded number of threads/API requests.
    """

    if max_concurrency < 1:
        raise ValueError("max_concurrency must be at least 1")

    results_by_index: list[RequestResult | None] = [None] * len(requests)
    pending: list[tuple[int, InputRequest]] = []
    for index, request in enumerate(requests):
        if checkpoint is not None:
            restored = checkpoint.get_success(request)
            if restored is not None:
                restored = RequestResult(
                    id=request.id,
                    channel=request.channel,
                    timestamp=request.timestamp,
                    classification=restored.classification,
                )
                results_by_index[index] = restored
                if metrics is not None:
                    metrics.record_result(restored, 0.0)
                logger.info("Resumed request %s from checkpoint", request.id)
                continue
        pending.append((index, request))

    async def classify_and_checkpoint(
        index: int, request: InputRequest
    ) -> tuple[int, RequestResult]:
        result = await asyncio.to_thread(classifier.classify_request, request)
        if checkpoint is not None:
            checkpoint.save(request, result)
        return index, result

    for start in range(0, len(pending), max_concurrency):
        batch = pending[start : start + max_concurrency]
        logger.info(
            "Processing async batch %s-%s/%s",
            start + 1,
            start + len(batch),
            len(pending),
        )
        batch_results = await asyncio.gather(
            *(classify_and_checkpoint(index, request) for index, request in batch)
        )
        for index, result in batch_results:
            results_by_index[index] = result

    return [result for result in results_by_index if result is not None]
