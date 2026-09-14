"""Canonical URL resolution and grouping.

design-options.md §5: aggregators wrap the same competition in their own
affiliate/tracking redirect, so the same comp shows up under several
different URLs. The fix is: follow redirects to the true destination, strip
tracking params, hash what's left. `source_count` (how many places listed a
comp) is kept as a ranking signal, not discarded as noise — see
`pipeline/normalise.py`, which merges the groups this module produces into
`Competition` rows.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from competition_hunter.models import RawListing

_TRACKING_PARAM_NAMES = {"ref", "fbclid", "gclid", "msclkid", "aff", "affiliate", "subid"}


def _is_tracking_param(name: str) -> bool:
    return name.lower().startswith("utm_") or name.lower() in _TRACKING_PARAM_NAMES


def strip_tracking_params(url: str) -> str:
    parts = urlsplit(url)
    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not _is_tracking_param(k)
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), ""))


def resolve_redirect(url: str, timeout: float = 10.0) -> str:
    """Follow HTTP redirects to the true destination URL.

    Falls back to the original URL on any network error — a source being
    briefly unreachable shouldn't sink the whole ingest run.
    """
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            response = client.head(url)
            return str(response.url)
    except httpx.HTTPError:
        return url


def canonicalize_url(url: str, *, resolve_redirects: bool = True) -> str:
    resolved = resolve_redirect(url) if resolve_redirects else url
    return strip_tracking_params(resolved)


def competition_id(canonical_url: str) -> str:
    return hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:16]


def group_by_canonical(
    listings: Iterable[RawListing], *, resolve_redirects: bool = True
) -> dict[str, list[RawListing]]:
    """Canonicalize each listing's link and group listings that land on the same one."""
    groups: dict[str, list[RawListing]] = defaultdict(list)
    for listing in listings:
        canonical_url = canonicalize_url(listing.link, resolve_redirects=resolve_redirects)
        groups[canonical_url].append(listing)
    return dict(groups)
