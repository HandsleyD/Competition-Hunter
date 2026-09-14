"""LLM-based enrichment: title + description -> structured fields.

design-options.md §5: reading free text and pulling out prize value, closing
date, restrictions and entry mechanic generalises far better than regex, and
it's cheap at this volume (a few hundred items a day) on a small/fast model.
Currently backed by Gemini (`competition_hunter/llm.py`) rather than
Anthropic, chosen for its no-payment-method free tier — which comes with a
real per-minute rate limit. A live run against a 1,248-item backlog hit a
429 on the 17th call fired back-to-back; REQUEST_INTERVAL_SECONDS paces
calls to stay under that, and `enrich_all` stops the batch (rather than
raising and losing everything already done) the moment a call fails for any
reason other than a malformed response, so whatever succeeded is still
persisted and the rest waits for the next scheduled run.

"Cache by competition_id, never re-enrich" (implementation-plan.md): the
caller is expected to run this only over `store.get_unenriched(conn)` and
persist every result — success or not — via `store.mark_enriched`, so a
competition already enriched is never sent to the LLM again.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel, ValidationError

from competition_hunter.models import Competition, EntryMechanic, RepeatInterval

logger = logging.getLogger(__name__)

# ~12 requests/minute — comfortably under the free tier's limit (observed
# failure at the 17th call fired with no pacing at all).
REQUEST_INTERVAL_SECONDS = 5.0

SYSTEM_PROMPT = """\
You extract structured facts about a UK prize competition from its listing \
title and description. Respond with a single JSON object only, matching this \
schema exactly - no prose, no markdown fences.

{
  "promoter": string or null,
  "prize_value_gbp": number or null (best estimate in GBP, no currency symbol),
  "closes_at": string or null (ISO 8601 date, e.g. "2026-12-31", if a closing date is stated),
  "entry_mechanic": one of "web_form", "gleam", "viralsweep", "rafflecopter", "social", \
"email", "postal", "unknown",
  "is_skill_based": boolean (true if entry requires answering a skill/tiebreaker question),
  "requires_purchase": boolean (true if a purchase is required to enter),
  "uk_only": boolean,
  "min_age": integer or null,
  "repeat_interval": one of "once", "daily", "weekly", "monthly", or null if not repeatable
}

If the text doesn't say, use null/false/"unknown" as appropriate. Never guess \
a prize value you can't support from the text."""


class Extraction(BaseModel):
    promoter: str | None = None
    prize_value_gbp: float | None = None
    closes_at: date | None = None
    entry_mechanic: EntryMechanic = "unknown"
    is_skill_based: bool = False
    requires_purchase: bool = False
    uk_only: bool = False
    min_age: int | None = None
    repeat_interval: RepeatInterval | None = None


class LLMClient(Protocol):
    """Whatever provider is behind enrichment just needs to answer a prompt
    with text back — a Protocol so tests can pass a stub and swapping the
    provider (see `competition_hunter/llm.py`) never touches this module."""

    def generate(self, *, system: str, prompt: str) -> str: ...


def extract(client: LLMClient, title: str, description: str) -> Extraction | None:
    """One enrichment call. Returns None (and logs) on any malformed response
    rather than raising, so one bad extraction never sinks a whole run — the
    competition is simply left unenriched for `mark_enriched` to record."""
    try:
        text = client.generate(
            system=SYSTEM_PROMPT,
            prompt=f"Title: {title}\n\nDescription: {description}",
        )
        return Extraction.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning("enrichment: could not parse a response for %r: %s", title, exc)
        return None


def apply_extraction(competition: Competition, extraction: Extraction) -> Competition:
    closes_at = (
        datetime.combine(extraction.closes_at, datetime.min.time(), tzinfo=UTC)
        if extraction.closes_at
        else None
    )
    prize_value_gbp = (
        Decimal(str(extraction.prize_value_gbp)) if extraction.prize_value_gbp is not None else None
    )
    return competition.model_copy(
        update={
            "promoter": extraction.promoter,
            "prize_value_gbp": prize_value_gbp,
            "closes_at": closes_at,
            "entry_mechanic": extraction.entry_mechanic,
            "is_skill_based": extraction.is_skill_based,
            "requires_purchase": extraction.requires_purchase,
            "uk_only": extraction.uk_only,
            "min_age": extraction.min_age,
            "repeat_interval": extraction.repeat_interval,
        }
    )


def enrich_all(client: LLMClient, competitions: Iterable[Competition]) -> list[Competition]:
    """Run one enrichment call per competition, paced to stay under the free
    tier's rate limit.

    A malformed response (`extract` returns None) just passes the
    competition through unchanged — that's a normal, expected outcome.
    Anything else `extract` raises (a 429, a timeout, ...) means the API
    itself is unhappy and every subsequent call will likely fail the same
    way, so the batch stops there rather than burning through the rest of
    the backlog on certain failures. Either way, only the competitions
    already processed are returned; the caller (`cli.run`) marks exactly
    those as enriched, and whatever's left stays unenriched for the next
    scheduled run to pick up.
    """
    results = []
    for i, competition in enumerate(competitions):
        if i > 0:
            time.sleep(REQUEST_INTERVAL_SECONDS)
        try:
            extraction = extract(client, competition.title, competition.description)
        except Exception:
            logger.warning(
                "enrichment: API call failed, stopping this batch early (%d done)", len(results)
            )
            break
        results.append(apply_extraction(competition, extraction) if extraction else competition)
    return results
