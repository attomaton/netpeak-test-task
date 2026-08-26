"""Unit tests for strict classification models."""

import pytest
from pydantic import ValidationError

from src.models import Category, ClassificationResult, Priority


def valid_payload() -> dict:
    return {
        "category": "автоматизація",
        "target_department": None,
        "priority": "medium",
        "short_summary": "Автоматизувати щотижневий звіт.",
        "requested_actions": ["Забирати дані", "Формувати звіт"],
        "needs_clarification": False,
        "clarification_question": None,
    }


def test_valid_payload_is_parsed_with_enums() -> None:
    result = ClassificationResult.model_validate(valid_payload())
    assert result.category is Category.AUTOMATION
    assert result.priority is Priority.MEDIUM


def test_invalid_enum_is_rejected() -> None:
    payload = valid_payload()
    payload["category"] = "spam"
    with pytest.raises(ValidationError):
        ClassificationResult.model_validate(payload)


def test_clarification_question_is_required_for_unclear_request() -> None:
    payload = valid_payload()
    payload["needs_clarification"] = True
    with pytest.raises(ValidationError):
        ClassificationResult.model_validate(payload)

