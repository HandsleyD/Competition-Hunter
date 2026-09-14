from datetime import UTC, datetime

from competition_hunter.models import Competition, RawListing


def raw_listing(
    *,
    source_name: str = "test-source",
    link: str = "https://example.com/comp",
    title: str = "Test Competition",
    description: str = "",
    published_at: datetime | None = None,
) -> RawListing:
    return RawListing(
        source_name=source_name,
        source_url=link,
        title=title,
        description=description,
        link=link,
        published_at=published_at or datetime(2026, 1, 1, tzinfo=UTC),
    )


def competition(**overrides) -> Competition:
    defaults = dict(
        id="abc123",
        canonical_url="https://example.com/comp",
        source_urls=["https://example.com/comp"],
        source_count=1,
        title="Test Competition",
        first_seen=datetime(2026, 1, 1, tzinfo=UTC),
    )
    defaults.update(overrides)
    return Competition(**defaults)
