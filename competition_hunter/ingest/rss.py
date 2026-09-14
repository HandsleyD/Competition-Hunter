"""RSS/Atom feed ingest — ThePrizeFinder and equivalents.

design-options.md §3A picks ThePrizeFinder's `/feeds` as the spine: structured,
stable, and published explicitly for consumption by software.

NOTE: this Claude Code environment's egress proxy blocks theprizefinder.com
(design-options.md §4), so the exact feed URLs below could not be confirmed
live from here — confirm against https://www.theprizefinder.com/feeds before
the first real run (GitHub Actions has open network access and is where this
runs in production). `parse_feed` is unit-tested against a recorded fixture
in tests/fixtures/ and does not depend on the URLs being right.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from time import struct_time

import feedparser
import httpx

from competition_hunter.models import RawListing

USER_AGENT = "competition-hunter/0.1 (+https://github.com/handsleyd/competition-hunter)"

# Verify against https://www.theprizefinder.com/feeds — see module docstring.
THEPRIZEFINDER_FEEDS: dict[str, str] = {
    "theprizefinder-new": "https://www.theprizefinder.com/feeds/new",
    "theprizefinder-top-prizes": "https://www.theprizefinder.com/feeds/top-prizes",
    "theprizefinder-closing-soon": "https://www.theprizefinder.com/feeds/closing-soon",
}


def _to_datetime(parsed_time: struct_time | None) -> datetime | None:
    if parsed_time is None:
        return None
    return datetime(*parsed_time[:6], tzinfo=UTC)


def parse_feed(content: bytes, source_name: str) -> list[RawListing]:
    """Parse raw feed bytes into listings. Pure and fixture-testable."""
    parsed = feedparser.parse(content)
    return [
        RawListing(
            source_name=source_name,
            source_url=entry.get("link", ""),
            title=entry.get("title", "").strip(),
            description=entry.get("summary", "").strip(),
            link=entry.get("link", ""),
            published_at=_to_datetime(entry.get("published_parsed")),
        )
        for entry in parsed.entries
    ]


class RssSource:
    """Fetches one RSS/Atom feed over HTTP and parses it."""

    def __init__(self, name: str, url: str, timeout: float = 15.0) -> None:
        self.name = name
        self.url = url
        self.timeout = timeout

    def fetch(self) -> Iterable[RawListing]:
        response = httpx.get(self.url, timeout=self.timeout, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        return parse_feed(response.content, self.name)


def default_sources() -> list[RssSource]:
    return [RssSource(name=name, url=url) for name, url in THEPRIZEFINDER_FEEDS.items()]
