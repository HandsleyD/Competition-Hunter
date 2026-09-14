"""RawListing -> Competition, merging groups that dedupe.py resolved to one URL.

Phase 1 has no LLM enrichment yet (that's `pipeline/enrich.py`, phase 2), so
the fields it would fill in — promoter, prize value, entry mechanic,
restrictions — stay at their defaults here.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from competition_hunter.models import Competition, RawListing
from competition_hunter.pipeline.dedupe import competition_id, group_by_canonical


def _merge(canonical_url: str, listings: list[RawListing]) -> Competition:
    source_urls = sorted({listing.source_url for listing in listings})
    published_dates = [listing.published_at for listing in listings if listing.published_at]
    first_seen = min(published_dates) if published_dates else datetime.now(UTC)
    return Competition(
        id=competition_id(canonical_url),
        canonical_url=canonical_url,
        source_urls=source_urls,
        source_count=len(source_urls),
        title=listings[0].title,
        first_seen=first_seen,
    )


def normalise_and_dedupe(
    listings: Iterable[RawListing], *, resolve_redirects: bool = True
) -> list[Competition]:
    groups = group_by_canonical(listings, resolve_redirects=resolve_redirects)
    return [_merge(url, group) for url, group in groups.items()]
