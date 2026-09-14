from dataclasses import dataclass

import httpx

from competition_hunter.pipeline.dedupe import (
    canonicalize_url,
    competition_id,
    group_by_canonical,
    resolve_redirect,
    strip_slug_suffix,
    strip_tracking_params,
)
from tests.factories import raw_listing


@dataclass
class _FakeResponse:
    url: str


def test_strip_tracking_params_removes_utm_and_known_tracking_names():
    url = "https://example.com/comp?utm_source=feed&utm_medium=rss&ref=aff123&id=42"

    assert strip_tracking_params(url) == "https://example.com/comp?id=42"


def test_strip_tracking_params_keeps_normal_query_params():
    url = "https://example.com/comp?id=42&region=uk"

    assert strip_tracking_params(url) == "https://example.com/comp?id=42&region=uk"


def test_canonicalize_url_without_redirect_resolution():
    url = "https://example.com/comp?utm_source=feed"

    assert canonicalize_url(url, resolve_redirects=False) == "https://example.com/comp"


def test_strip_slug_suffix_removes_a_trailing_numeric_disambiguator():
    # Real example: ThePrizeFinder lists the same competition twice under
    # .../win-sleep-well-hamper-worth-over-ps260 and .../...-ps260-0.
    url = "https://www.theprizefinder.com/competitions/win-sleep-well-hamper-worth-over-ps260-0"

    assert (
        strip_slug_suffix(url)
        == "https://www.theprizefinder.com/competitions/win-sleep-well-hamper-worth-over-ps260"
    )


def test_strip_slug_suffix_leaves_a_slug_with_no_numeric_suffix_alone():
    url = "https://www.theprizefinder.com/competitions/win-sleep-well-hamper-worth-over-ps260"

    assert strip_slug_suffix(url) == url


def test_canonicalize_url_collapses_the_real_duplicate_pair():
    a = "https://www.theprizefinder.com/competitions/win-sleep-well-hamper-worth-over-ps260"
    b = "https://www.theprizefinder.com/competitions/win-sleep-well-hamper-worth-over-ps260-0"

    assert canonicalize_url(a, resolve_redirects=False) == canonicalize_url(
        b, resolve_redirects=False
    )


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


def test_group_by_canonical_merges_a_slug_disambiguated_duplicate():
    listings = [
        raw_listing(
            source_name="a",
            link="https://www.theprizefinder.com/competitions/win-sleep-well-hamper-worth-over-ps260",
        ),
        raw_listing(
            source_name="b",
            link="https://www.theprizefinder.com/competitions/win-sleep-well-hamper-worth-over-ps260-0",
        ),
    ]

    groups = group_by_canonical(listings, resolve_redirects=False)

    assert len(groups) == 1
    assert sum(len(v) for v in groups.values()) == 2


def test_resolve_redirect_falls_back_to_original_url_on_network_error(monkeypatch):
    def raise_error(self, url, *args, **kwargs):
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(httpx.Client, "head", raise_error)

    assert resolve_redirect("https://example.com/comp") == "https://example.com/comp"


def test_group_by_canonical_resolves_redirects_for_many_listings_via_shared_client(monkeypatch):
    # Simulates an aggregator wrapping a handful of real competitions behind
    # many different tracking links — the shape that made a serial,
    # one-client-per-listing redirect lookup take 10+ minutes against the
    # real feeds. This exercises the concurrent, shared-client code path
    # entirely against a mocked httpx.Client.head, with no real network.
    call_count = 0

    def fake_head(self, url, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        slug = url.split("/out/")[-1].split("?")[0]
        return _FakeResponse(url=f"https://promoter.example/comp/{slug}")

    monkeypatch.setattr(httpx.Client, "head", fake_head)

    listings = [
        raw_listing(
            source_name=f"agg-{i}",
            link=f"https://agg{i}.example/out/{i % 3}?utm_source=x",
        )
        for i in range(12)
    ]

    groups = group_by_canonical(listings, resolve_redirects=True)

    assert call_count == 12
    assert set(groups) == {
        "https://promoter.example/comp/0",
        "https://promoter.example/comp/1",
        "https://promoter.example/comp/2",
    }
    assert sum(len(v) for v in groups.values()) == 12
