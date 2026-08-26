"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name, str(default)).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean.")


@dataclass(frozen=True)
class Settings:
    """Runtime settings for the classifier application."""

    provider: str
    api_key: str
    model: str
    max_attempts: int
    retry_backoff_seconds: float
    max_concurrency: int
    rate_limit_requests_per_window: int
    rate_limit_window_seconds: float
    cache_enabled: bool
    cache_file: Path
    checkpoint_enabled: bool
    checkpoint_file: Path
    human_review_enabled: bool
    review_file: Path
    monitoring_enabled: bool
    monitoring_file: Path
    fallback_enabled: bool
    fallback_provider: str
    gemini_fallback_model: str
    google_sheets_enabled: bool
    google_service_account_file: Path | None
    google_sheet_id: str
    google_worksheet_name: str
    telegram_enabled: bool
    telegram_bot_token: str
    telegram_chat_id: str
    telegram_timeout_seconds: float

    @classmethod
    def from_env(cls, env_file: str | Path = ".env") -> "Settings":
        """Load settings from a local dotenv file and process environment."""

        load_dotenv(env_file)
        provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
        max_attempts = int(os.getenv("MAX_ATTEMPTS", "3"))
        retry_backoff_seconds = float(os.getenv("RETRY_BACKOFF_SECONDS", "1.0"))
        max_concurrency = int(os.getenv("MAX_CONCURRENCY", "4"))
        rate_limit_requests = int(os.getenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "15"))
        rate_limit_window = float(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))

        cache_enabled = _env_bool("CACHE_ENABLED", True)
        cache_file = Path(os.getenv("CACHE_FILE", ".cache/classifications.json").strip())
        checkpoint_enabled = _env_bool("CHECKPOINT_ENABLED", True)
        checkpoint_file = Path(os.getenv("CHECKPOINT_FILE", ".cache/checkpoint.json").strip())
        human_review_enabled = _env_bool("HUMAN_REVIEW_ENABLED", True)
        review_file = Path(os.getenv("REVIEW_FILE", "review_queue.json").strip())
        monitoring_enabled = _env_bool("MONITORING_ENABLED", True)
        monitoring_file = Path(os.getenv("MONITORING_FILE", "metrics.json").strip())

        fallback_enabled = _env_bool("LLM_FALLBACK_ENABLED", False)
        fallback_provider = os.getenv("LLM_FALLBACK_PROVIDER", "heuristic").strip().lower()
        gemini_fallback_model = os.getenv("GEMINI_FALLBACK_MODEL", "").strip()

        sheets_enabled = _env_bool("GOOGLE_SHEETS_ENABLED", False)
        service_account_raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
        sheet_id = os.getenv("GOOGLE_SHEET_ID", "").strip()
        worksheet_name = os.getenv(
            "GOOGLE_WORKSHEET_NAME", "classification_results"
        ).strip()

        telegram_enabled = _env_bool("TELEGRAM_ENABLED", False)
        telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        telegram_timeout = float(os.getenv("TELEGRAM_TIMEOUT_SECONDS", "15"))

        if provider != "gemini":
            raise ValueError(
                f"Unsupported LLM_PROVIDER={provider!r}. This project supports only 'gemini'."
            )
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set. Copy .env.example to .env and add it.")
        if not model:
            raise ValueError("GEMINI_MODEL cannot be empty.")
        if max_attempts < 1 or max_attempts > 3:
            raise ValueError("MAX_ATTEMPTS must be between 1 and 3.")
        if retry_backoff_seconds < 0:
            raise ValueError("RETRY_BACKOFF_SECONDS cannot be negative.")
        if max_concurrency < 1 or max_concurrency > 20:
            raise ValueError("MAX_CONCURRENCY must be between 1 and 20.")
        if rate_limit_requests < 0:
            raise ValueError("RATE_LIMIT_REQUESTS_PER_MINUTE cannot be negative.")
        if rate_limit_window <= 0:
            raise ValueError("RATE_LIMIT_WINDOW_SECONDS must be positive.")
        if fallback_provider not in {"heuristic", "gemini"}:
            raise ValueError("LLM_FALLBACK_PROVIDER must be 'heuristic' or 'gemini'.")
        if fallback_enabled and fallback_provider == "gemini" and not gemini_fallback_model:
            raise ValueError("GEMINI_FALLBACK_MODEL is required for Gemini fallback.")
        if sheets_enabled:
            if not service_account_raw:
                raise ValueError(
                    "GOOGLE_SERVICE_ACCOUNT_FILE is required when Sheets is enabled."
                )
            if not sheet_id:
                raise ValueError("GOOGLE_SHEET_ID is required when Sheets is enabled.")
            if not worksheet_name:
                raise ValueError("GOOGLE_WORKSHEET_NAME cannot be empty.")
        if telegram_enabled and (not telegram_token or not telegram_chat_id):
            raise ValueError(
                "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required when Telegram is enabled."
            )
        if telegram_timeout <= 0:
            raise ValueError("TELEGRAM_TIMEOUT_SECONDS must be positive.")

        return cls(
            provider=provider,
            api_key=api_key,
            model=model,
            max_attempts=max_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
            max_concurrency=max_concurrency,
            rate_limit_requests_per_window=rate_limit_requests,
            rate_limit_window_seconds=rate_limit_window,
            cache_enabled=cache_enabled,
            cache_file=cache_file,
            checkpoint_enabled=checkpoint_enabled,
            checkpoint_file=checkpoint_file,
            human_review_enabled=human_review_enabled,
            review_file=review_file,
            monitoring_enabled=monitoring_enabled,
            monitoring_file=monitoring_file,
            fallback_enabled=fallback_enabled,
            fallback_provider=fallback_provider,
            gemini_fallback_model=gemini_fallback_model,
            google_sheets_enabled=sheets_enabled,
            google_service_account_file=(
                Path(service_account_raw) if service_account_raw else None
            ),
            google_sheet_id=sheet_id,
            google_worksheet_name=worksheet_name,
            telegram_enabled=telegram_enabled,
            telegram_bot_token=telegram_token,
            telegram_chat_id=telegram_chat_id,
            telegram_timeout_seconds=telegram_timeout,
        )
