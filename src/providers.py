"""Provider composition and an explicit opt-in local fallback."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any

logger = logging.getLogger(__name__)


class FallbackLLMClient:
    """Try providers in order and expose the last failure if all fail."""

    def __init__(
        self,
        clients: Sequence[Any],
        on_fallback: Callable[[], None] | None = None,
    ) -> None:
        if not clients:
            raise ValueError("at least one provider is required")
        self.clients = list(clients)
        self.on_fallback = on_fallback

    def classify(self, raw_text: str) -> Any:
        last_error: Exception | None = None
        for index, client in enumerate(self.clients):
            try:
                if index > 0 and self.on_fallback is not None:
                    self.on_fallback()
                return client.classify(raw_text)
            except Exception as exc:
                last_error = exc
                if index + 1 < len(self.clients):
                    logger.warning(
                        "Primary LLM provider failed; trying fallback %s: %s",
                        index + 1,
                        type(exc).__name__,
                    )
        assert last_error is not None
        raise last_error


class HeuristicFallbackClient:
    """Conservative offline fallback whose output always enters human review.

    It keeps the pipeline operational during provider outages but is not meant
    to silently replace an LLM-quality decision.
    """

    def classify(self, raw_text: str) -> dict[str, Any]:
        text = raw_text.casefold()
        if not text.strip():
            raise ValueError("empty request")
        if any(word in text for word in ("дякую", "спасибі", "thanks", "все працює")):
            category = "поза скоупом"
        elif any(word in text for word in ("злам", "помил", "не працю", "баг")):
            category = "баг/підтримка"
        elif any(word in text for word in ("інтеграц", "інтегра", "slack", "planfix")):
            category = "інтеграція"
        elif any(word in text for word in ("звіт", "дашборд", "аналітик", "метрик")):
            category = "звіт/аналітика"
        elif any(word in text for word in ("можна", "питання", "реально", "думка")):
            category = "питання/консультація"
        else:
            category = "автоматизація"

        high = any(word in text for word in ("терміново", "горить", "сьогодні", "зупин"))
        return {
            "category": category,
            "target_department": None,
            "priority": "high" if high else "medium",
            "short_summary": "Потрібна ручна перевірка класифікації запиту.",
            "requested_actions": [],
            "needs_clarification": True,
            "clarification_question": "Підтвердьте категорію, пріоритет та очікуваний результат запиту.",
        }


def build_fallback_client(
    primary: Any,
    enabled: bool,
    provider: str,
    fallback_model: str,
    api_key: str,
    on_fallback: Callable[[], None] | None = None,
) -> Any:
    """Build an opt-in fallback without changing the default Gemini path."""

    if not enabled:
        return primary
    if provider == "heuristic":
        return FallbackLLMClient([primary, HeuristicFallbackClient()], on_fallback)
    if provider == "gemini":
        if not fallback_model:
            raise ValueError("GEMINI_FALLBACK_MODEL is required for Gemini fallback")
        from .llm_client import GeminiLLMClient

        return FallbackLLMClient(
            [primary, GeminiLLMClient(api_key=api_key, model=fallback_model)],
            on_fallback,
        )
    raise ValueError(f"Unsupported LLM_FALLBACK_PROVIDER={provider!r}")
