from pathlib import Path

from competition_hunter.ingest.rss import parse_feed

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_feed_extracts_listings():
    content = (FIXTURES / "theprizefinder_new.xml").read_bytes()

    listings = parse_feed(content, source_name="theprizefinder-new")

    assert len(listings) == 2
    first = listings[0]
    assert first.source_name == "theprizefinder-new"
    assert first.title == "Win a Family Trip to Lapland"
    assert (
        first.link
        == "https://www.theprizefinder.com/out/lapland-trip?utm_source=feed&utm_medium=rss"
    )
    assert "Lapland" in first.description
    assert first.published_at is not None
    assert first.published_at.year == 2026


def test_parse_feed_empty_on_no_entries():
    content = b"""<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>"""

    assert parse_feed(content, source_name="empty") == []
