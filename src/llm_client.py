"""Small Google Gemini adapter with structured-output configuration."""

from __future__ import annotations

from typing import Any

from .models import ClassificationResult
from .prompt import SYSTEM_PROMPT, build_user_prompt


class GeminiLLMClient:
    """Call Gemini using the official google-genai SDK."""

    def __init__(self, api_key: str, model: str, temperature: float = 0.1) -> None:
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:  # pragma: no cover - exercised in setup, not unit tests
            raise RuntimeError(
                "google-genai is not installed. Install dependencies from requirements.txt."
            ) from exc

        self._types = types
        self.model = model
        self.temperature = temperature
        self.client = genai.Client(api_key=api_key)

    def classify(self, raw_text: str) -> Any:
        """Return parsed SDK output when available, otherwise its JSON text."""

        response = self.client.models.generate_content(
            model=self.model,
            contents=build_user_prompt(raw_text),
            config=self._types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=self.temperature,
                response_mime_type="application/json",
                response_schema=ClassificationResult,
            ),
        )

        parsed = getattr(response, "parsed", None)
        if parsed is not None:
            return parsed
        response_text = getattr(response, "text", None)
        if not response_text:
            raise ValueError("Gemini returned an empty response")
        return response_text

