"""Pydantic data model shared across ingest, pipeline and store.

See docs/implementation-plan.md for the field-by-field rationale.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

EntryMechanic = Literal[
    "web_form", "gleam", "viralsweep", "rafflecopter", "social", "email", "postal", "unknown"
]
RepeatInterval = Literal["once", "daily", "weekly", "monthly"]
EntryOutcome = Literal["submitted", "queued_manual", "failed", "skipped", "dry_run"]


class RawListing(BaseModel):
    """A single item as it comes off a source, before normalisation."""

    source_name: str
    source_url: str
    title: str
    description: str = ""
    link: str
    published_at: datetime | None = None


class Competition(BaseModel):
    id: str  # hash of canonical_url
    canonical_url: str  # redirects followed, tracking params stripped
    source_urls: list[str] = Field(default_factory=list)
    source_count: int = 0  # negative ranking signal — see design §5
    title: str
    description: str = ""  # kept for enrichment; not shown on the dashboard
    enriched: bool = False  # LLM extraction attempted — never re-enrich, see pipeline/enrich.py
    promoter: str | None = None
    prize_value_gbp: Decimal | None = None
    closes_at: datetime | None = None
    entry_mechanic: EntryMechanic = "unknown"
    is_skill_based: bool = False  # tiebreaker question -> strong odds signal
    requires_purchase: bool = False
    uk_only: bool = False
    min_age: int | None = None
    repeat_interval: RepeatInterval | None = None
    score: float = 0.0
    first_seen: datetime


class EntryAttempt(BaseModel):
    competition_id: str
    attempted_at: datetime
    outcome: EntryOutcome
    reason: str | None = None


class Consent(BaseModel):
    marketing: bool = False
    third_party: bool = False
    terms_accepted: bool = True


class Limits(BaseModel):
    max_entries_per_run: int = 40
    max_entries_per_domain: int = 1
    min_delay_seconds: int = 20
    max_delay_seconds: int = 90


class EmailMessage(BaseModel):
    """A single email as fetched from the wins-ledger mailbox, before
    classification. See competition_hunter/wins/mailbox.py."""

    message_id: str
    received_at: datetime
    subject: str
    sender: str
    body_text: str = ""


class Win(BaseModel):
    """One classified email, win or not — doubles as the dedupe ledger so
    the same email is never reprocessed. See competition_hunter/wins/."""

    message_id: str
    received_at: datetime
    subject: str
    sender: str
    is_win: bool
    competition_id: str | None = None
    prize_description: str = ""
    confidence: float = 0.0
    created_at: datetime


class Profile(BaseModel):
    """Loaded from profile.toml — never enters the repo, CI, or a log line."""

    title: str
    first_name: str
    last_name: str
    dob: str
    email: str
    phone: str
    line1: str
    town: str
    postcode: str
    country: str = "United Kingdom"
    line2: str = ""
    county: str = ""
    consent: Consent = Field(default_factory=Consent)
    limits: Limits = Field(default_factory=Limits)
