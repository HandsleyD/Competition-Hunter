"""Thin wrapper around the Gemini API for enrichment.

Chosen over the Anthropic API for this project because Gemini's free tier
needs no payment method to get started, which matters for a personal-scale
hobby project run on someone's own GitHub Actions minutes. See
`pipeline/enrich.py` for the thing that actually calls this.
"""

from __future__ import annotations

from google import genai
from google.genai import types

# "-latest" aliases to Google's current recommended Flash model rather than
# pinning an exact dated version, which Google renames/deprecates over time.
# Verify against https://ai.google.dev/gemini-api/docs/models if this project
# ever needs to pin an exact version instead.
MODEL = "gemini-flash-latest"


class GeminiClient:
    """The provider-specific half of `pipeline.enrich.LLMClient`."""

    def __init__(self, api_key: str) -> None:
        self._client = genai.Client(api_key=api_key)

    def generate(self, *, system: str, prompt: str) -> str:
        response = self._client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
            ),
        )
        return response.text
