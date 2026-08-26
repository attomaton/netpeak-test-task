"""Report aggregation tests."""

from src.models import ClassificationResult, ProcessingError, RequestResult
from src.report import build_report


def success(id_: str, category: str, priority: str, department: str | None, clarify: bool = False):
    return RequestResult(
        id=id_,
        channel="Slack",
        timestamp="2026-06-08 10:00",
        classification=ClassificationResult(
            category=category,
            target_department=department,
            priority=priority,
            short_summary="Потрібно виконати запит.",
            requested_actions=[],
            needs_clarification=clarify,
            clarification_question="Який саме результат потрібен?" if clarify else None,
        ),
    )


def test_report_contains_required_aggregates_and_clarifications() -> None:
    results = [
        success("REQ-1", "автоматизація", "medium", "маркетинг"),
        success("REQ-2", "звіт/аналітика", "low", None, clarify=True),
        RequestResult(
            id="REQ-3",
            channel="Email",
            timestamp="2026-06-08 10:00",
            error=ProcessingError(type="JSONDecodeError", message="bad json", attempts=3),
        ),
    ]
    report = build_report(results)
    assert "Всего запросов: **3**" in report
    assert "| автоматизація | 1 |" in report
    assert "| звіт/аналітика | 1 |" in report
    assert "| medium | 1 |" in report
    assert "| Не определено | 1 |" in report
    assert "REQ-2" in report
    assert "Ошибок обработки: **1**" in report

