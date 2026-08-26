"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    """Runtime settings for the classifier application."""

    provider: str
    api_key: str
    model: str
    temperature: float
    max_attempts: int
    retry_backoff_seconds: float

    @classmethod
    def from_env(cls, env_file: str | Path = ".env") -> "Settings":
        """Load settings from a local dotenv file and process environment."""

        load_dotenv(env_file)
        provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
        temperature = float(os.getenv("LLM_TEMPERATURE", "0.1"))
        max_attempts = int(os.getenv("MAX_ATTEMPTS", "3"))
        retry_backoff_seconds = float(os.getenv("RETRY_BACKOFF_SECONDS", "1.0"))

        if provider != "gemini":
            raise ValueError(
                f"Unsupported LLM_PROVIDER={provider!r}. This project supports only 'gemini'."
            )
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set. Copy .env.example to .env and add it.")
        if not model:
            raise ValueError("GEMINI_MODEL cannot be empty.")
        if not 0 <= temperature <= 1:
            raise ValueError("LLM_TEMPERATURE must be between 0 and 1.")
        if max_attempts < 1 or max_attempts > 5:
            raise ValueError("MAX_ATTEMPTS must be between 1 and 5.")
        if retry_backoff_seconds < 0:
            raise ValueError("RETRY_BACKOFF_SECONDS cannot be negative.")

        return cls(
            provider=provider,
            api_key=api_key,
            model=model,
            temperature=temperature,
            max_attempts=max_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
        )

