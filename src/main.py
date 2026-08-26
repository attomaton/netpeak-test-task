"""CLI entry point for the request classification pipeline."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from .async_processing import classify_requests_async
from .classifier import RequestClassifier
from .config import Settings
from .integrations import GoogleSheetsExporter, TelegramDigestSender
from .io_utils import load_requests, write_output
from .llm_client import GeminiLLMClient
from .report import build_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Classify internal requests with Gemini.")
    parser.add_argument("--input", type=Path, default=Path("input_requests.csv"))
    parser.add_argument("--output", type=Path, default=Path("output.json"))
    parser.add_argument("--report", type=Path, default=Path("report.md"))
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

    llm_client = GeminiLLMClient(
        api_key=settings.api_key,
        model=settings.model,
    )
    classifier = RequestClassifier(
        llm_client=llm_client,
        max_attempts=settings.max_attempts,
        backoff_seconds=settings.retry_backoff_seconds,
        api_key=settings.api_key,
    )
    results = asyncio.run(
        classify_requests_async(
            requests,
            classifier,
            max_concurrency=settings.max_concurrency,
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
    publish_optional_integrations(results, settings, logger)


if __name__ == "__main__":
    main()
