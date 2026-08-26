"""Atomic checkpoint storage for resumable batch processing."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from .cache import raw_text_hash
from .models import InputRequest, RequestResult


class CheckpointStore:
    """Persist each completed item and reuse only matching successful results."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def get_success(self, request: InputRequest) -> RequestResult | None:
        """Return a checkpointed success for the same request text, if present."""

        with self._lock:
            payload = self._read_locked()
        item = payload.get("items", {}).get(request.id)
        if not isinstance(item, dict):
            return None
        if item.get("raw_text_hash") != raw_text_hash(request.raw_text):
            return None
        result_payload = item.get("result")
        if not isinstance(result_payload, dict):
            return None
        try:
            result = RequestResult.model_validate(result_payload)
        except Exception:
            return None
        return result if result.classification is not None else None

    def save(self, request: InputRequest, result: RequestResult) -> None:
        """Save one result with an input fingerprint and replace atomically."""

        with self._lock:
            payload = self._read_locked()
            payload.setdefault("version", 1)
            payload.setdefault("items", {})
            payload["items"][request.id] = {
                "raw_text_hash": raw_text_hash(request.raw_text),
                "result": result.model_dump(mode="json"),
            }
            self._write_locked(payload)

    def _read_locked(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "items": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": 1, "items": {}}
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), dict):
            return {"version": 1, "items": {}}
        return payload

    def _write_locked(self, payload: dict[str, Any]) -> None:
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
                json.dump(payload, temporary, ensure_ascii=False, indent=2)
                temporary.write("\n")
                temporary_path = temporary.name
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)

