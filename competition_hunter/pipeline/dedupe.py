"""Canonical URL resolution and grouping.

design-options.md §5: aggregators wrap the same competition in their own
affiliate/tracking redirect, so the same comp shows up under several
different URLs. The fix is: follow redirects to the true destination, strip
tracking params and slug-collision suffixes, hash what's left. `source_count`
(how many places listed a comp) is kept as a ranking signal, not discarded
as noise — see `pipeline/normalise.py`, which merges the groups this module
produces into `Competition` rows.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from competition_hunter.models import RawListing

_TRACKING_PARAM_NAMES = {"ref", "fbclid", "gclid", "msclkid", "aff", "affiliate", "subid"}

# ThePrizeFinder (and sites like it) append "-0", "-1", ... to a listing's
# URL slug when two entries would otherwise generate an identical one - e.g.
# a repeat-run competition re-listed under the same title. Confirmed on the
# live site: .../win-sleep-well-hamper-worth-over-ps260 and the same
# .../...-ps260-0 are the same competition, not two different ones.
_SLUG_SUFFIX_RE = re.compile(r"-\d+$")

# Redirect resolution is one HTTP request per listing, and a real feed run
# can have hundreds of listings. A short per-request timeout and a bounded
# thread pool keep the worst case bounded (roughly N/POOL_SIZE * TIMEOUT)
# instead of serial — a run against live feeds once took 10+ minutes and
# climbing before this existed.
_REDIRECT_TIMEOUT_SECONDS = 5.0
_REDIRECT_POOL_SIZE = 10


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


def strip_slug_suffix(url: str) -> str:
    parts = urlsplit(url)
    path = _SLUG_SUFFIX_RE.sub("", parts.path)
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def resolve_redirect(url: str, client: httpx.Client | None = None) -> str:
    """Follow HTTP redirects to the true destination URL.

    Falls back to the original URL on any network error — a source being
    briefly unreachable shouldn't sink the whole ingest run. Reuses `client`
    when given (connection pooling across a batch); opens and closes its own
    otherwise, for one-off callers.
    """
    owned_client = client is None
    client = client or httpx.Client(follow_redirects=True, timeout=_REDIRECT_TIMEOUT_SECONDS)
    try:
        response = client.head(url)
        return str(response.url)
    except httpx.HTTPError:
        return url
    finally:
        if owned_client:
            client.close()


def canonicalize_url(
    url: str, *, resolve_redirects: bool = True, client: httpx.Client | None = None
) -> str:
    resolved = resolve_redirect(url, client=client) if resolve_redirects else url
    return strip_slug_suffix(strip_tracking_params(resolved))


def group_by_canonical(
    listings: Iterable[RawListing], *, resolve_redirects: bool = True
) -> dict[str, list[RawListing]]:
    """Canonicalize each listing's link and group listings that land on the same one."""
    listings = list(listings)

    if resolve_redirects:
        with (
            httpx.Client(follow_redirects=True, timeout=_REDIRECT_TIMEOUT_SECONDS) as client,
            ThreadPoolExecutor(max_workers=_REDIRECT_POOL_SIZE) as pool,
        ):
            canonical_urls = list(
                pool.map(lambda listing: resolve_redirect(listing.link, client=client), listings)
            )
        canonical_urls = [strip_slug_suffix(strip_tracking_params(url)) for url in canonical_urls]
    else:
        canonical_urls = [
            canonicalize_url(listing.link, resolve_redirects=False) for listing in listings
        ]

    groups: dict[str, list[RawListing]] = defaultdict(list)
    for listing, canonical_url in zip(listings, canonical_urls, strict=True):
        groups[canonical_url].append(listing)
    return dict(groups)


def competition_id(canonical_url: str) -> str:
    return hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:16]
