"""Newsletter-inbox ingest: an aggregator digest email -> RawListings.

design-options.md §3B: subscribing a dedicated inbox to aggregator
newsletters (ThePrizeFinder, Loquax, Competitions Time, Competition
Database — see docs/setup-accounts.md) gets pre-curated listings with none
of RSS's brittleness — you're the intended recipient, so there's no
scraping, no robots.txt question, nothing to break when a site redesigns.

A `Source` (ingest.base.Source protocol) like ingest/rss.py, but backed by
`competition_hunter.mailbox.ImapMailbox` instead of an HTTP feed URL, since
a newsletter digest bundles many competitions into one email rather than
one-listing-per-entry the way an RSS item does — extracting them needs an
LLM call, not a feed parser.

Local-only per implementation-plan.md's trust split, same as the entry
layer and the wins ledger: mailbox.toml holds a real IMAP password, so
unlike ingest/rss.py this never runs from cli.py's CI path
(discover_local.py is the local-only entrypoint that wires this in).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from datetime import date, timedelta

from pydantic import BaseModel, ValidationError

from competition_hunter.mailbox import ImapMailbox
from competition_hunter.models import EmailMessage, RawListing
from competition_hunter.pipeline.enrich import LLMClient

logger = logging.getLogger(__name__)

# A digest can be long; the listings themselves are near the top, and this
# keeps the call cheap — same reasoning as wins/classify.py's body cap.
_MAX_BODY_CHARS = 8000

SYSTEM_PROMPT = """\
You extract every individual UK prize competition listed in one aggregator \
newsletter digest email. Respond with a single JSON array only - no prose, \
no markdown fences - one object per competition:

[{"title": string, "link": string (the URL to enter or read more; "" if \
none given), "description": string (a short summary, or "")}]

Ignore anything that is not itself a competition - header/footer \
boilerplate, adverts, unsubscribe links, "last week's winners" sections. If \
the email lists no competitions, respond with an empty array []."""


class _ListingExtraction(BaseModel):
    title: str = ""
    link: str = ""
    description: str = ""


def extract_listings(client: LLMClient, email: EmailMessage) -> list[RawListing]:
    """One LLM call per newsletter email. Returns no listings (rather than
    raising) on a malformed response, or for an item missing a title/link —
    one bad or unparseable newsletter shouldn't sink a whole ingest run."""
    try:
        text = client.generate(system=SYSTEM_PROMPT, prompt=email.body_text[:_MAX_BODY_CHARS])
        raw = json.loads(text)
        if not isinstance(raw, list):
            raise ValueError("response was not a JSON array")
        extractions = [_ListingExtraction.model_validate(item) for item in raw]
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        logger.warning("newsletter: could not parse listings from %r: %s", email.subject, exc)
        return []

    return [
        RawListing(
            source_name=f"newsletter:{email.sender}",
            source_url=item.link,
            title=item.title,
            description=item.description,
            link=item.link,
            published_at=email.received_at,
        )
        for item in extractions
        if item.title and item.link
    ]


class NewsletterSource:
    """A `Source` backed by the dedicated inbox's newsletter digests rather
    than a live feed URL."""

    name = "newsletter"

    def __init__(self, mailbox: ImapMailbox, client: LLMClient, *, since_days: int = 7) -> None:
        self._mailbox = mailbox
        self._client = client
        self._since_days = since_days

    def fetch(self) -> Iterable[RawListing]:
        since = date.today() - timedelta(days=self._since_days)
        listings: list[RawListing] = []
        for email in self._mailbox.fetch_since(since):
            listings.extend(extract_listings(self._client, email))
        return listings
