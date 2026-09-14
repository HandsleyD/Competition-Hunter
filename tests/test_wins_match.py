from datetime import UTC, datetime

import pytest

from competition_hunter import store
from competition_hunter.models import EntryAttempt
from competition_hunter.wins.classify import WinClassification
from competition_hunter.wins.match import find_matching_competition
from tests.factories import competition


@pytest.fixture
def conn(tmp_path):
    connection = store.connect(tmp_path / "test.db")
    yield connection
    connection.close()


def _enter(conn, comp):
    store.upsert_competition(conn, comp)
    store.record_entry_attempt(
        conn,
        EntryAttempt(competition_id=comp.id, attempted_at=datetime.now(UTC), outcome="submitted"),
    )


def test_finds_a_close_title_match(conn):
    _enter(conn, competition(id="hamper", title="Win a Luxury Hamper Worth £200"))

    match = find_matching_competition(
        conn, WinClassification(is_win=True, competition_title_guess="Luxury Hamper Giveaway")
    )

    assert match is not None
    assert match.id == "hamper"


def test_returns_none_when_nothing_is_close_enough(conn):
    _enter(conn, competition(id="hamper", title="Win a Luxury Hamper"))

    match = find_matching_competition(
        conn, WinClassification(is_win=True, competition_title_guess="A completely unrelated prize")
    )

    assert match is None


def test_returns_none_when_the_guess_is_empty(conn):
    _enter(conn, competition(id="hamper", title="Win a Luxury Hamper"))

    match = find_matching_competition(conn, WinClassification(is_win=True))

    assert match is None


def test_never_matches_a_competition_that_was_never_entered(conn):
    store.upsert_competition(conn, competition(id="hamper", title="Win a Luxury Hamper"))

    match = find_matching_competition(
        conn, WinClassification(is_win=True, competition_title_guess="Win a Luxury Hamper")
    )

    assert match is None


def test_picks_the_best_match_among_several_candidates(conn):
    _enter(conn, competition(id="a", canonical_url="https://a.example", title="Win a Hamper"))
    _enter(
        conn,
        competition(
            id="b", canonical_url="https://b.example", title="Win a Luxury Hamper Giveaway 2026"
        ),
    )

    match = find_matching_competition(
        conn, WinClassification(is_win=True, competition_title_guess="Luxury Hamper Giveaway")
    )

    assert match.id == "b"
