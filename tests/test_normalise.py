from datetime import UTC, datetime

from competition_hunter.pipeline.normalise import normalise_and_dedupe
from tests.factories import raw_listing


def test_merges_same_competition_from_two_sources_and_keeps_source_count():
    listings = [
        raw_listing(
            source_name="theprizefinder-new",
            link="https://example.com/comp?utm_source=new",
            title="Win a Trip",
            published_at=datetime(2026, 9, 7, tzinfo=UTC),
        ),
        raw_listing(
            source_name="theprizefinder-closing-soon",
            link="https://example.com/comp?utm_source=closing-soon&ref=aff",
            title="Win a Trip",
            published_at=datetime(2026, 9, 9, tzinfo=UTC),
        ),
    ]

    competitions = normalise_and_dedupe(listings, resolve_redirects=False)

    assert len(competitions) == 1
    comp = competitions[0]
    assert comp.canonical_url == "https://example.com/comp"
    assert comp.source_count == 2
    assert comp.first_seen == datetime(2026, 9, 7, tzinfo=UTC)  # earliest sighting wins


def test_keeps_distinct_competitions_separate():
    listings = [
        raw_listing(link="https://example.com/comp-a", title="A"),
        raw_listing(link="https://example.com/comp-b", title="B"),
    ]

    competitions = normalise_and_dedupe(listings, resolve_redirects=False)

    assert {c.title for c in competitions} == {"A", "B"}
    assert all(c.source_count == 1 for c in competitions)


def test_carries_description_through_for_enrichment():
    listings = [raw_listing(link="https://example.com/comp", description="Win a shiny thing.")]

    [comp] = normalise_and_dedupe(listings, resolve_redirects=False)

    assert comp.description == "Win a shiny thing."


def test_picks_first_non_empty_description_when_merging():
    listings = [
        raw_listing(source_name="a", link="https://example.com/comp?utm_source=a", description=""),
        raw_listing(
            source_name="b",
            link="https://example.com/comp?utm_source=b",
            description="Full details here.",
        ),
    ]

    [comp] = normalise_and_dedupe(listings, resolve_redirects=False)

    assert comp.description == "Full details here."
