"""LLM classification of a single email: is this a win notification?

Reuses `pipeline.enrich.LLMClient` — same "answer a prompt with text" shape,
so this needs no provider-specific code of its own.
"""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel, ValidationError

from competition_hunter.models import EmailMessage
from competition_hunter.pipeline.enrich import LLMClient

logger = logging.getLogger(__name__)

# A win notification says what it needs to in the first paragraph; anything
# past this is unlikely to change the classification and only costs tokens.
_MAX_BODY_CHARS = 4000

SYSTEM_PROMPT = """\
You read one email and decide whether it is a genuine notification that the \
recipient has won a UK prize competition - not a newsletter, not a receipt, \
not routine marketing, and not a phishing/scam "you've won!" message (those \
typically ask for payment or banking/personal details up front, or come \
from a sender unrelated to any competition). Respond with a single JSON \
object only - no prose, no markdown fences.

{
  "is_win": boolean,
  "competition_title_guess": string (best guess at the competition's name \
as it would have appeared when entering, or "" if not a win),
  "prize_description": string (what was won, or "" if not a win),
  "promoter": string (who is awarding it, or "" if not a win),
  "confidence": number between 0 and 1
}"""


class WinClassification(BaseModel):
    is_win: bool = False
    competition_title_guess: str = ""
    prize_description: str = ""
    promoter: str = ""
    confidence: float = 0.0


def classify_email(client: LLMClient, email: EmailMessage) -> WinClassification:
    """One LLM call. Returns a confident "not a win" (rather than raising) on
    a malformed response — the caller still marks the email processed, so
    it's never retried on a later run."""
    prompt = (
        f"Subject: {email.subject}\nFrom: {email.sender}\n\n{email.body_text[:_MAX_BODY_CHARS]}"
    )
    try:
        text = client.generate(system=SYSTEM_PROMPT, prompt=prompt)
        return WinClassification.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning("wins: could not parse a classification for %r: %s", email.subject, exc)
        return WinClassification()
