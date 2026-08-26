"""CLI entry point for the request classification pipeline."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from .async_processing import classify_requests_async
from .cache import ClassificationCache
from .checkpoint import CheckpointStore
from .classifier import RequestClassifier
from .config import Settings
from .integrations import GoogleSheetsExporter, TelegramDigestSender
from .io_utils import load_requests, write_output
from .llm_client import GeminiLLMClient
from .monitoring import MetricsCollector
from .providers import build_fallback_client
from .rate_limit import QuotaAwareRateLimiter
from .report import build_report
from .review import build_review_queue


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Classify internal requests with Gemini.")
    parser.add_argument("--input", type=Path, default=Path("input_requests.csv"))
    parser.add_argument("--output", type=Path, default=Path("output.json"))
    parser.add_argument("--report", type=Path, default=Path("report.md"))
    parser.add_argument("--checkpoint", type=Path, default=None)
    parser.add_argument("--cache", type=Path, default=None)
    parser.add_argument("--review-output", type=Path, default=None)
    parser.add_argument("--metrics-output", type=Path, default=None)
    return parser.parse_args()


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def publish_optional_integrations(results, settings: Settings, logger: logging.Logger) -> None:
    """Best-effort external publishing after local artifacts are safely written."""

    if settings.google_sheets_enabled:
        assert settings.google_service_account_file is not None
        try:
            rows = GoogleSheetsExporter(
                service_account_file=settings.google_service_account_file,
                spreadsheet_id=settings.google_sheet_id,
                worksheet_name=settings.google_worksheet_name,
            ).export(results)
            logger.info("Exported %s rows to Google Sheets", rows)
        except Exception:
            logger.exception(
                "Google Sheets export failed; local output.json/report.md are preserved"
            )

    if settings.telegram_enabled:
        try:
            messages = TelegramDigestSender(
                bot_token=settings.telegram_bot_token,
                chat_id=settings.telegram_chat_id,
                timeout_seconds=settings.telegram_timeout_seconds,
            ).send(results)
            logger.info("Sent Telegram digest in %s message(s)", messages)
        except Exception:
            logger.exception(
                "Telegram digest failed; local output.json/report.md are preserved"
            )


def main() -> None:
    configure_logging()
    args = parse_args()
    logger = logging.getLogger(__name__)
    settings = Settings.from_env()
    requests = load_requests(args.input)
    logger.info("Loaded %s requests from %s", len(requests), args.input)

    metrics = MetricsCollector()
    primary_client = GeminiLLMClient(api_key=settings.api_key, model=settings.model)
    llm_client = build_fallback_client(
        primary=primary_client,
        enabled=settings.fallback_enabled,
        provider=settings.fallback_provider,
        fallback_model=settings.gemini_fallback_model,
        api_key=settings.api_key,
        on_fallback=metrics.record_fallback,
    )
    cache = (
        ClassificationCache(args.cache or settings.cache_file)
        if settings.cache_enabled
        else None
    )
    checkpoint = (
        CheckpointStore(args.checkpoint or settings.checkpoint_file)
        if settings.checkpoint_enabled
        else None
    )
    rate_limiter = QuotaAwareRateLimiter(
        requests_per_window=settings.rate_limit_requests_per_window,
        window_seconds=settings.rate_limit_window_seconds,
    )
    classifier = RequestClassifier(
        llm_client=llm_client,
        max_attempts=settings.max_attempts,
        backoff_seconds=settings.retry_backoff_seconds,
        api_key=settings.api_key,
        cache=cache,
        rate_limiter=rate_limiter,
        metrics=metrics,
    )
    results = asyncio.run(
        classify_requests_async(
            requests,
            classifier,
            max_concurrency=settings.max_concurrency,
            checkpoint=checkpoint,
            metrics=metrics,
        )
    )

    write_output(args.output, results)
    args.report.write_text(build_report(results), encoding="utf-8")
    logger.info(
        "Finished processing %s requests; output=%s report=%s",
        len(results),
        args.output,
        args.report,
    )
    if settings.human_review_enabled:
        try:
            review_count = build_review_queue(
                requests,
                results,
                args.review_output or settings.review_file,
            )
            logger.info("Wrote %s item(s) to human review queue", review_count)
        except Exception:
            logger.exception("Human review queue failed; local output/report are preserved")
    if settings.monitoring_enabled:
        try:
            metrics.write(args.metrics_output or settings.monitoring_file, len(requests))
            logger.info("Wrote monitoring metrics")
        except Exception:
            logger.exception("Monitoring metrics failed; local output/report are preserved")
    publish_optional_integrations(results, settings, logger)


if __name__ == "__main__":
    main()
