from competition_hunter.pipeline.dedupe import (
    canonicalize_url,
    competition_id,
    group_by_canonical,
    strip_tracking_params,
)
from tests.factories import raw_listing


def test_strip_tracking_params_removes_utm_and_known_tracking_names():
    url = "https://example.com/comp?utm_source=feed&utm_medium=rss&ref=aff123&id=42"

    assert strip_tracking_params(url) == "https://example.com/comp?id=42"


def test_strip_tracking_params_keeps_normal_query_params():
    url = "https://example.com/comp?id=42&region=uk"

    assert strip_tracking_params(url) == "https://example.com/comp?id=42&region=uk"


def test_canonicalize_url_without_redirect_resolution():
    url = "https://example.com/comp?utm_source=feed"

    assert canonicalize_url(url, resolve_redirects=False) == "https://example.com/comp"


def test_competition_id_is_stable_and_content_derived():
    a = competition_id("https://example.com/comp")
    b = competition_id("https://example.com/comp")
    c = competition_id("https://example.com/other")

    assert a == b
    assert a != c


def test_group_by_canonical_merges_listings_with_same_canonical_url():
    listings = [
        raw_listing(source_name="a", link="https://example.com/comp?utm_source=a"),
        raw_listing(source_name="b", link="https://example.com/comp?utm_source=b"),
        raw_listing(source_name="c", link="https://example.com/other?utm_source=c"),
    ]

    groups = group_by_canonical(listings, resolve_redirects=False)

    assert set(groups) == {"https://example.com/comp", "https://example.com/other"}
    assert len(groups["https://example.com/comp"]) == 2
    assert len(groups["https://example.com/other"]) == 1
