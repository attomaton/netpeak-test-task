"""Input and output data models with strict local validation."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Category(str, Enum):
    AUTOMATION = "автоматизація"
    INTEGRATION = "інтеграція"
    REPORTING = "звіт/аналітика"
    SUPPORT = "баг/підтримка"
    CONSULTATION = "питання/консультація"
    OUT_OF_SCOPE = "поза скоупом"


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class InputRequest(BaseModel):
    """One row from input_requests.csv."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    timestamp: str = Field(min_length=1)
    raw_text: str = Field(min_length=1)

    @field_validator("id", "channel", "timestamp", "raw_text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be blank")
        return value


class ClassificationResult(BaseModel):
    """The only accepted successful LLM classification shape."""

    model_config = ConfigDict(extra="forbid")

    category: Category
    target_department: str | None = None
    priority: Priority
    short_summary: str = Field(min_length=1)
    requested_actions: list[str]
    needs_clarification: bool
    clarification_question: str | None = None

    @field_validator("short_summary")
    @classmethod
    def validate_summary(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("short_summary cannot be blank")
        return value

    @field_validator("target_department", "clarification_question")
    @classmethod
    def normalize_nullable_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("requested_actions")
    @classmethod
    def validate_actions(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for action in value:
            if not isinstance(action, str) or not action.strip():
                raise ValueError("requested_actions must contain non-empty strings")
            cleaned.append(action.strip())
        return cleaned

    @model_validator(mode="after")
    def validate_clarification_pair(self) -> "ClassificationResult":
        if self.needs_clarification and not self.clarification_question:
            raise ValueError(
                "clarification_question is required when needs_clarification is true"
            )
        if not self.needs_clarification and self.clarification_question is not None:
            raise ValueError(
                "clarification_question must be null when needs_clarification is false"
            )
        return self


class ProcessingError(BaseModel):
    """A transparent, per-request processing failure."""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1)
    message: str = Field(min_length=1)
    attempts: int = Field(ge=1)


class RequestResult(BaseModel):
    """Input metadata plus either a classification or an explicit error."""

    model_config = ConfigDict(extra="forbid")

    id: str
    channel: str
    timestamp: str
    classification: ClassificationResult | None = None
    error: ProcessingError | None = None

    @model_validator(mode="after")
    def require_one_outcome(self) -> "RequestResult":
        if (self.classification is None) == (self.error is None):
            raise ValueError("exactly one of classification or error must be present")
        return self


def parse_llm_output(raw_output: Any) -> ClassificationResult:
    """Parse either structured SDK output, a dict, or a JSON string locally."""

    if isinstance(raw_output, ClassificationResult):
        return raw_output
    if isinstance(raw_output, str):
        return ClassificationResult.model_validate_json(raw_output)
    if isinstance(raw_output, dict):
        return ClassificationResult.model_validate(raw_output)
    raise TypeError(f"Unsupported LLM output type: {type(raw_output).__name__}")

