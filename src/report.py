"""Deterministic Markdown aggregation generated from processed results."""

from __future__ import annotations

from collections import Counter

from .models import Category, Priority, RequestResult


def _markdown_table(counter: Counter[str], ordered_values: list[str] | None = None) -> str:
    values = ordered_values or sorted(counter)
    lines = ["| Значение | Количество |", "|---|---:|"]
    lines.extend(f"| {value} | {counter.get(value, 0)} |" for value in values)
    return "\n".join(lines)


def build_report(results: list[RequestResult]) -> str:
    """Build all required aggregates from results, including zero-count enums."""

    successful = [item.classification for item in results if item.classification is not None]
    category_counts = Counter(item.category.value for item in successful)
    priority_counts = Counter(item.priority.value for item in successful)
    department_counts = Counter(
        item.target_department or "Не определено" for item in successful
    )
    clarification_items = [
        item
        for item in results
        if item.classification is not None and item.classification.needs_clarification
    ]
    errors = [item for item in results if item.error is not None]

    category_values = [category.value for category in Category]
    priority_values = [priority.value for priority in Priority]
    lines = [
        "# Отчёт по классификации внутренних запросов",
        "",
        f"Всего запросов: **{len(results)}**",
        f"Успешно классифицировано: **{len(successful)}**",
        f"Ошибок обработки: **{len(errors)}**",
        "",
        "## Количество по category",
        "",
        _markdown_table(category_counts, category_values),
        "",
        "## Количество по priority",
        "",
        _markdown_table(priority_counts, priority_values),
        "",
        "## Количество по target_department",
        "",
        _markdown_table(department_counts),
        "",
        "## Запросы, требующие уточнения",
        "",
    ]

    if clarification_items:
        lines.extend(
            [
                "| ID | Краткая суть | Уточняющий вопрос |",
                "|---|---|---|",
            ]
        )
        for item in clarification_items:
            classification = item.classification
            assert classification is not None
            question = classification.clarification_question or "—"
            lines.append(
                f"| {item.id} | {classification.short_summary} | {question} |"
            )
    else:
        lines.append("Нет запросов, требующих уточнения.")

    if errors:
        lines.extend(["", "## Ошибки обработки", "", "| ID | Тип | Попытки | Сообщение |", "|---|---|---:|---|"])
        for item in errors:
            error = item.error
            assert error is not None
            lines.append(f"| {item.id} | {error.type} | {error.attempts} | {error.message} |")

    return "\n".join(lines) + "\n"

