"""Optional Google Sheets export and Telegram digest integrations."""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .models import Category, Priority, RequestResult

logger = logging.getLogger(__name__)

SHEET_HEADERS = [
    "id",
    "channel",
    "timestamp",
    "category",
    "target_department",
    "priority",
    "short_summary",
    "requested_actions",
    "needs_clarification",
    "clarification_question",
    "error_type",
    "error_message",
]


def result_to_sheet_row(result: RequestResult) -> list[str]:
    """Flatten one result for a human-readable sheet row."""

    if result.classification is not None:
        classification = result.classification
        return [
            result.id,
            result.channel,
            result.timestamp,
            classification.category.value,
            classification.target_department or "",
            classification.priority.value,
            classification.short_summary,
            "; ".join(classification.requested_actions),
            str(classification.needs_clarification).lower(),
            classification.clarification_question or "",
            "",
            "",
        ]

    error = result.error
    assert error is not None
    return [
        result.id,
        result.channel,
        result.timestamp,
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        error.type,
        error.message,
    ]


class GoogleSheetsExporter:
    """Replace one configured worksheet with the latest batch result."""

    def __init__(
        self,
        service_account_file: Path,
        spreadsheet_id: str,
        worksheet_name: str = "classification_results",
        service_account_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.service_account_file = service_account_file
        self.spreadsheet_id = spreadsheet_id
        self.worksheet_name = worksheet_name
        self.service_account_factory = service_account_factory

    def export(self, results: list[RequestResult]) -> int:
        """Write headers and rows in one update; return the number of rows."""

        try:
            import gspread
            from gspread.exceptions import WorksheetNotFound
        except ImportError as exc:  # pragma: no cover - setup error
            raise RuntimeError("Install gspread to enable Google Sheets export.") from exc

        factory = self.service_account_factory or gspread.service_account
        client = factory(filename=str(self.service_account_file))
        spreadsheet = client.open_by_key(self.spreadsheet_id)
        try:
            worksheet = spreadsheet.worksheet(self.worksheet_name)
        except WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(
                title=self.worksheet_name,
                rows=max(len(results) + 1, 100),
                cols=len(SHEET_HEADERS),
            )

        worksheet.clear()
        worksheet.update(
            "A1",
            [SHEET_HEADERS, *(result_to_sheet_row(result) for result in results)],
            value_input_option="USER_ENTERED",
        )
        return len(results)


def build_telegram_digest(results: list[RequestResult]) -> str:
    """Build a compact digest without copying raw internal messages."""

    successful = [result.classification for result in results if result.classification]
    errors = [result for result in results if result.error]
    category_counts = Counter(item.category.value for item in successful)
    priority_counts = Counter(item.priority.value for item in successful)
    clarification_ids = [
        result.id
        for result in results
        if result.classification and result.classification.needs_clarification
    ]

    lines = [
        "📊 Підсумок класифікації запитів",
        f"Всього: {len(results)} | успішно: {len(successful)} | помилок: {len(errors)}",
        "",
        "Категорії:",
    ]
    lines.extend(
        f"• {category.value}: {category_counts.get(category.value, 0)}"
        for category in Category
    )
    lines.extend(["", "Пріоритети:"])
    lines.extend(
        f"• {priority.value}: {priority_counts.get(priority.value, 0)}"
        for priority in Priority
    )
    lines.extend(["", f"Потребують уточнення: {len(clarification_ids)}"])
    if clarification_ids:
        lines.append("ID: " + ", ".join(clarification_ids[:20]))
    return "\n".join(lines)


def split_telegram_message(text: str, max_length: int = 4000) -> list[str]:
    """Split digest safely below Telegram's 4096-character message limit."""

    if max_length < 1:
        raise ValueError("max_length must be positive")
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break
        split_at = remaining.rfind("\n", 0, max_length + 1)
        if split_at <= 0:
            split_at = max_length
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip("\n")
    return chunks or [""]


class TelegramDigestSender:
    """Send the generated digest through the Telegram Bot API."""

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        timeout_seconds: float = 15.0,
        http_client_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout_seconds = timeout_seconds
        self.http_client_factory = http_client_factory

    def send(self, results: list[RequestResult]) -> int:
        """Send all chunks and return the number of Telegram messages sent."""

        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - setup error
            raise RuntimeError("Install httpx to enable Telegram digest sending.") from exc

        factory = self.http_client_factory or httpx.Client
        chunks = split_telegram_message(build_telegram_digest(results))
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        with factory(timeout=self.timeout_seconds) as client:
            for chunk in chunks:
                response = client.post(
                    url,
                    data={
                        "chat_id": self.chat_id,
                        "text": chunk,
                        "disable_web_page_preview": "true",
                    },
                )
                response.raise_for_status()
                payload = response.json()
                if not payload.get("ok"):
                    raise RuntimeError("Telegram API returned ok=false")
        return len(chunks)

