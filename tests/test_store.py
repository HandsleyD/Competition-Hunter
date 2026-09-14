from datetime import UTC, datetime

import pytest

from competition_hunter import store
from competition_hunter.models import Competition, EntryAttempt


@pytest.fixture
def conn(tmp_path):
    connection = store.connect(tmp_path / "test.db")
    yield connection
    connection.close()


def _competition(**overrides) -> Competition:
    defaults = dict(
        id="abc123",
        canonical_url="https://example.com/comp",
        source_urls=["https://example.com/comp?utm_source=a"],
        source_count=1,
        title="Win a Trip",
        first_seen=datetime(2026, 9, 7, tzinfo=UTC),
    )
    defaults.update(overrides)
    return Competition(**defaults)


def test_upsert_inserts_new_competition(conn):
    store.upsert_competition(conn, _competition())

    rows = store.get_competitions(conn)
    assert len(rows) == 1
    assert rows[0].id == "abc123"
    assert rows[0].source_count == 1


def test_upsert_merges_source_urls_and_keeps_earliest_first_seen(conn):
    store.upsert_competition(conn, _competition())
    later_sighting = _competition(
        source_urls=["https://example.com/comp?utm_source=b"],
        first_seen=datetime(2026, 9, 9, tzinfo=UTC),
    )

    merged = store.upsert_competition(conn, later_sighting)

    assert merged.source_count == 2
    assert merged.first_seen == datetime(2026, 9, 7, tzinfo=UTC)
    assert len(store.get_competitions(conn)) == 1


def test_record_entry_attempt_and_entered_today(conn):
    store.upsert_competition(conn, _competition())
    today = datetime.now(UTC)

    assert store.entered_today(conn, "abc123") is False

    store.record_entry_attempt(
        conn,
        EntryAttempt(competition_id="abc123", attempted_at=today, outcome="submitted"),
    )

    assert store.entered_today(conn, "abc123") is True


def test_entered_today_ignores_non_submitted_outcomes(conn):
    store.upsert_competition(conn, _competition())
    store.record_entry_attempt(
        conn,
        EntryAttempt(
            competition_id="abc123",
            attempted_at=datetime.now(UTC),
            outcome="skipped",
            reason="requires purchase",
        ),
    )

    assert store.entered_today(conn, "abc123") is False


def test_get_competitions_orders_by_closes_at_nulls_last(conn):
    store.upsert_competition(conn, _competition(id="no-close", closes_at=None))
    store.upsert_competition(
        conn,
        _competition(
            id="closes-soon",
            canonical_url="https://example.com/other",
            closes_at=datetime(2026, 9, 10, tzinfo=UTC),
        ),
    )

    ordered = store.get_competitions(conn, order_by="closes_at")

    assert [c.id for c in ordered] == ["closes-soon", "no-close"]
