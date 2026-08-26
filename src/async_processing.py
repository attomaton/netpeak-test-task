"""Bounded async/batch orchestration for independent LLM requests."""

from __future__ import annotations

import asyncio
import logging

from .classifier import RequestClassifier
from .models import InputRequest, RequestResult

logger = logging.getLogger(__name__)


async def classify_requests_async(
    requests: list[InputRequest],
    classifier: RequestClassifier,
    max_concurrency: int = 4,
) -> list[RequestResult]:
    """Process bounded batches concurrently while preserving input order.

    The Gemini SDK call is synchronous, so each call runs in a worker thread.
    Batches avoid creating an unbounded number of threads/API requests.
    """

    if max_concurrency < 1:
        raise ValueError("max_concurrency must be at least 1")

    results: list[RequestResult] = []
    for start in range(0, len(requests), max_concurrency):
        batch = requests[start : start + max_concurrency]
        logger.info(
            "Processing async batch %s-%s/%s",
            start + 1,
            start + len(batch),
            len(requests),
        )
        batch_results = await asyncio.gather(
            *(asyncio.to_thread(classifier.classify_request, request) for request in batch)
        )
        results.extend(batch_results)

    return results

