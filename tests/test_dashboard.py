from datetime import UTC, datetime, timedelta
from decimal import Decimal

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


def test_build_sorts_by_score_descending(tmp_path):
    competitions = [
        _competition(id="low", canonical_url="https://example.com/a", title="Low", score=1.0),
        _competition(id="high", canonical_url="https://example.com/b", title="High", score=9.0),
        _competition(id="mid", canonical_url="https://example.com/c", title="Mid", score=5.0),
    ]

    index_path = build(competitions, tmp_path)
    html = index_path.read_text()

    assert html.index("High") < html.index("Mid") < html.index("Low")


def test_build_shows_promoter_and_prize(tmp_path):
    competitions = [_competition(promoter="Acme Ltd", prize_value_gbp=Decimal("250"))]

    index_path = build(competitions, tmp_path)
    html = index_path.read_text()

    assert "Acme Ltd" in html
    assert "£250" in html


def test_build_shows_dash_for_unenriched_promoter_and_prize(tmp_path):
    competitions = [_competition(promoter=None, prize_value_gbp=None)]

    index_path = build(competitions, tmp_path)
    html = index_path.read_text()

    assert "—" in html


def test_build_flags_closing_soon(tmp_path):
    now = datetime.now(UTC)
    competitions = [_competition(closes_at=now + timedelta(hours=12))]

    index_path = build(competitions, tmp_path)

    assert 'class="closing-soon"' in index_path.read_text()


def test_build_handles_no_competitions(tmp_path):
    index_path = build([], tmp_path)

    assert "No competitions ingested yet" in index_path.read_text()


def test_build_shows_repeatables_tracker_when_present(tmp_path):
    index_path = build([_competition()], tmp_path, repeatables=(3, 7))

    html = index_path.read_text()
    assert "3" in html
    assert "7" in html
    assert "done today" in html


def test_build_hides_repeatables_tracker_when_none(tmp_path):
    index_path = build([_competition()], tmp_path, repeatables=(0, 0))

    assert "done today" not in index_path.read_text()
