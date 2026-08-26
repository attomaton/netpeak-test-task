"""CLI entry point for the request classification pipeline."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .classifier import RequestClassifier, classify_requests
from .config import Settings
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
        temperature=settings.temperature,
    )
    classifier = RequestClassifier(
        llm_client=llm_client,
        max_attempts=settings.max_attempts,
        backoff_seconds=settings.retry_backoff_seconds,
        api_key=settings.api_key,
    )
    results = classify_requests(requests, classifier)
    write_output(args.output, results)
    args.report.write_text(build_report(results), encoding="utf-8")
    logger.info(
        "Finished processing %s requests; output=%s report=%s",
        len(results),
        args.output,
        args.report,
    )


if __name__ == "__main__":
    main()

