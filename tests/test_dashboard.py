from datetime import UTC, datetime, timedelta

from competition_hunter.dashboard.build import build
from competition_hunter.models import Competition


def _competition(**overrides) -> Competition:
    defaults = dict(
        id="abc123",
        canonical_url="https://example.com/comp",
        source_urls=["https://example.com/comp"],
        source_count=1,
        title="Win a Trip",
        first_seen=datetime(2026, 9, 7, tzinfo=UTC),
    )
    defaults.update(overrides)
    return Competition(**defaults)


def test_build_writes_index_html_with_competition_titles(tmp_path):
    competitions = [_competition(title="Win a Trip to Lapland")]

    index_path = build(competitions, tmp_path)

    assert index_path.exists()
    html = index_path.read_text()
    assert "Win a Trip to Lapland" in html
    assert "https://example.com/comp" in html


def test_build_sorts_by_closing_date_soonest_first(tmp_path):
    now = datetime.now(UTC)
    competitions = [
        _competition(
            id="later",
            canonical_url="https://example.com/b",
            title="Later",
            closes_at=now + timedelta(days=10),
        ),
        _competition(
            id="sooner",
            canonical_url="https://example.com/a",
            title="Sooner",
            closes_at=now + timedelta(days=1),
        ),
        _competition(
            id="open-ended",
            canonical_url="https://example.com/c",
            title="OpenEnded",
            closes_at=None,
        ),
    ]

    index_path = build(competitions, tmp_path)

    html = index_path.read_text()
    assert html.index("Sooner") < html.index("Later") < html.index("OpenEnded")


def test_build_flags_closing_soon(tmp_path):
    now = datetime.now(UTC)
    competitions = [_competition(closes_at=now + timedelta(hours=12))]

    index_path = build(competitions, tmp_path)

    assert 'class="closing-soon"' in index_path.read_text()


def test_build_handles_no_competitions(tmp_path):
    index_path = build([], tmp_path)

    assert "No competitions ingested yet" in index_path.read_text()
