"""Thin wrapper around the Gemini API for enrichment.

Chosen over the Anthropic API for this project because Gemini's free tier
needs no payment method to get started, which matters for a personal-scale
hobby project run on someone's own GitHub Actions minutes. See
`pipeline/enrich.py` for the thing that actually calls this, including the
rate-limit pacing that lives there.
"""

from __future__ import annotations

import logging

from google import genai
from google.genai import errors, types

logger = logging.getLogger(__name__)

# Ordered most-to-least capable/available on the free tier, per the project
# owner's own aistudio.google.com rate-limit page (checked 2026-09-14):
#   gemini-3.5-flash-lite:  15 RPM, 500 RPD  (primary)
#   gemini-2.5-flash-lite:  10 RPM,  20 RPD
#   gemini-3-flash:          5 RPM,  20 RPD
#   gemini-2.5-flash:        5 RPM,  20 RPD
# gemini-2-flash, gemini-2-flash-lite and gemini-2.5-pro all showed 0/0 on
# that page (unavailable on this tier) and are deliberately left out.
MODEL_FALLBACK_CHAIN = [
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-3-flash",
    "gemini-2.5-flash",
]


class GeminiClient:
    """The provider-specific half of `pipeline.enrich.LLMClient`.

    Each model on the free tier has its own separate RPM/RPD quota, so one
    being exhausted doesn't mean they all are. On a 429 this falls back to
    the next model in `MODEL_FALLBACK_CHAIN` rather than giving up, and
    stays on whatever it falls back to for the rest of this client's
    lifetime — it doesn't retry an already-exhausted model on every call.
    Only once every model in the chain is rate-limited does a 429 finally
    propagate, for `pipeline.enrich.enrich_all` to handle.
    """

    def __init__(self, api_key: str, models: list[str] | None = None) -> None:
        self._client = genai.Client(api_key=api_key)
        self._models = list(models) if models is not None else list(MODEL_FALLBACK_CHAIN)
        self._model_index = 0

    def generate(self, *, system: str, prompt: str) -> str:
        while True:
            model = self._models[self._model_index]
            try:
                response = self._client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        response_mime_type="application/json",
                    ),
                )
                return response.text
            except errors.ClientError as exc:
                is_rate_limited = exc.code == 429
                has_fallback_left = self._model_index < len(self._models) - 1
                if is_rate_limited and has_fallback_left:
                    self._model_index += 1
                    logger.warning(
                        "%s rate-limited, falling back to %s",
                        model,
                        self._models[self._model_index],
                    )
                    continue
                raise
