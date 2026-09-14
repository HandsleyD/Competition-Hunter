from pathlib import Path

from competition_hunter.ingest.rss import parse_feed
from competition_hunter.pipeline.normalise import normalise_and_dedupe

FIXTURES = Path(__file__).parent / "fixtures"


def test_two_feeds_dedupe_the_shared_competition():
    new_listings = parse_feed(
        (FIXTURES / "theprizefinder_new.xml").read_bytes(), "theprizefinder-new"
    )
    closing_soon_listings = parse_feed(
        (FIXTURES / "theprizefinder_closing_soon.xml").read_bytes(),
        "theprizefinder-closing-soon",
    )

    competitions = normalise_and_dedupe(
        new_listings + closing_soon_listings, resolve_redirects=False
    )

    # 2 + 2 raw listings, but "Win a Family Trip to Lapland" is listed on both
    # feeds under different tracking params -> 3 distinct competitions.
    assert len(competitions) == 3

    lapland = next(c for c in competitions if "Lapland" in c.title)
    assert lapland.source_count == 2
    assert lapland.canonical_url == "https://www.theprizefinder.com/out/lapland-trip"
