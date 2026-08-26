"""Persistent cache for successful classifications."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
import unicodedata
from pathlib import Path

from .models import ClassificationResult

logger = logging.getLogger(__name__)


def normalize_raw_text(raw_text: str) -> str:
    """Normalize text so harmless whitespace/case differences share one key."""

    normalized = unicodedata.normalize("NFKC", raw_text)
    return " ".join(normalized.casefold().split())


def raw_text_hash(raw_text: str) -> str:
    """Return a stable, non-reversible cache key for normalized request text."""

    return hashlib.sha256(normalize_raw_text(raw_text).encode("utf-8")).hexdigest()


class ClassificationCache:
    """Small JSON cache suitable for a local batch and easy to inspect/remove."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data = self._load()

    def _load(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Ignoring unreadable cache %s: %s", self.path, exc)
            return {}

    def get(self, raw_text: str) -> ClassificationResult | None:
        key = raw_text_hash(raw_text)
        with self._lock:
            payload = self._data.get(key)
        if payload is None:
            return None
        try:
            return ClassificationResult.model_validate(payload)
        except Exception as exc:
            logger.warning("Ignoring invalid cached classification %s: %s", key, exc)
            return None

    def set(self, raw_text: str, classification: ClassificationResult) -> None:
        key = raw_text_hash(raw_text)
        with self._lock:
            self._data[key] = classification.model_dump(mode="json")
            self._write_locked()

    def _write_locked(self) -> None:
        payload = json.dumps(self._data, ensure_ascii=False, indent=2) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(payload)
                temporary_path = temporary.name
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)

