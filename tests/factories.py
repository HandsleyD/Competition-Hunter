from datetime import UTC, datetime

from competition_hunter.models import Competition, EmailMessage, Profile, RawListing


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


def email_message(**overrides) -> EmailMessage:
    defaults = dict(
        message_id="<msg-1@example.com>",
        received_at=datetime(2026, 1, 2, tzinfo=UTC),
        subject="Test subject",
        sender="promoter@example.com",
        body_text="Test body",
    )
    defaults.update(overrides)
    return EmailMessage(**defaults)


def profile(**overrides) -> Profile:
    """Entirely fictional test data - never real PII."""
    defaults = dict(
        title="Mx",
        first_name="Test",
        last_name="Testerson",
        dob="1990-06-15",
        email="test@example.com",
        phone="07700900000",
        line1="1 Example Street",
        town="Exampleton",
        postcode="EX4 1PL",
    )
    defaults.update(overrides)
    return Profile(**defaults)
