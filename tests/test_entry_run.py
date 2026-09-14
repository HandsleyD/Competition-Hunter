import json
import textwrap
from datetime import UTC, datetime, timedelta
from pathlib import Path

import playwright.sync_api as pw_api
import pytest

from competition_hunter import store
from competition_hunter.entry import run as entry_run
from competition_hunter.models import EntryAttempt
from tests.factories import competition

FIXTURES = Path(__file__).parent / "fixtures" / "forms"


@pytest.fixture(autouse=True)
def _fallback_browser_executable(monkeypatch):
    """This sandbox's pre-installed Chromium build doesn't always match the
    exact playwright version `uv add` resolves — fall back to the pinned
    binary only when the caller didn't already specify one. Never touches
    entry/run.py itself, which always launches plain `headless=True`."""
    original_launch = pw_api.BrowserType.launch

    def patched_launch(self, **kwargs):
        kwargs.setdefault("executable_path", "/opt/pw-browsers/chromium")
        return original_launch(self, **kwargs)

    monkeypatch.setattr(pw_api.BrowserType, "launch", patched_launch)


@pytest.fixture
def conn(tmp_path):
    connection = store.connect(tmp_path / "test.db")
    yield connection
    connection.close()


PROFILE_TOML = textwrap.dedent("""\
    [identity]
    title = "Mx"
    first_name = "Test"
    last_name = "Testerson"
    dob = "1990-06-15"

    [contact]
    email = "test@example.com"
    phone = "07700900000"

    [address]
    line1 = "1 Example Street"
    town = "Exampleton"
    postcode = "EX4 1PL"
    country = "United Kingdom"

    [consent]
    marketing = false
    third_party = false
    terms_accepted = true

    [limits]
    max_entries_per_run = 5
    max_entries_per_domain = 1
    min_delay_seconds = 0
    max_delay_seconds = 0
    """)


@pytest.fixture
def profile_path(tmp_path) -> Path:
    path = tmp_path / "profile.toml"
    path.write_text(PROFILE_TOML)
    return path


def test_load_profile_flattens_toml_sections(profile_path):
    profile = entry_run.load_profile(profile_path)

    assert profile.first_name == "Test"
    assert profile.email == "test@example.com"
    assert profile.line1 == "1 Example Street"
    assert profile.consent.marketing is False
    assert profile.consent.terms_accepted is True
    assert profile.limits.max_entries_per_run == 5


def _profile(**limits_overrides):
    from tests.factories import profile as make_profile

    prof = make_profile()
    if limits_overrides:
        prof = prof.model_copy(update={"limits": prof.limits.model_copy(update=limits_overrides)})
    return prof


class TestSelectCandidates:
    def test_selects_an_auto_routable_open_competition(self, conn):
        store.upsert_competition(conn, competition(entry_mechanic="web_form"))

        candidates = entry_run.select_candidates(conn, _profile())

        assert [c.id for c in candidates] == ["abc123"]

    def test_excludes_manual_queue_and_skip_routed_competitions(self, conn):
        store.upsert_competition(
            conn, competition(id="skill", canonical_url="https://a.example/x", is_skill_based=True)
        )
        store.upsert_competition(
            conn,
            competition(
                id="purchase",
                canonical_url="https://b.example/x",
                requires_purchase=True,
                entry_mechanic="web_form",
            ),
        )

        candidates = entry_run.select_candidates(conn, _profile())

        assert candidates == []

    def test_excludes_a_closed_competition(self, conn):
        store.upsert_competition(
            conn,
            competition(
                entry_mechanic="web_form",
                closes_at=datetime.now(UTC) - timedelta(days=1),
            ),
        )

        assert entry_run.select_candidates(conn, _profile()) == []

    def test_excludes_a_once_off_competition_already_entered(self, conn):
        store.upsert_competition(conn, competition(entry_mechanic="web_form"))
        store.record_entry_attempt(
            conn,
            EntryAttempt(
                competition_id="abc123", attempted_at=datetime.now(UTC), outcome="submitted"
            ),
        )

        assert entry_run.select_candidates(conn, _profile()) == []

    def test_includes_a_daily_repeatable_not_yet_entered_today(self, conn):
        store.upsert_competition(
            conn, competition(entry_mechanic="web_form", repeat_interval="daily")
        )
        # Entered yesterday, not today — still eligible.
        store.record_entry_attempt(
            conn,
            EntryAttempt(
                competition_id="abc123",
                attempted_at=datetime.now(UTC) - timedelta(days=1),
                outcome="submitted",
            ),
        )

        candidates = entry_run.select_candidates(conn, _profile())

        assert [c.id for c in candidates] == ["abc123"]

    def test_excludes_a_daily_repeatable_already_entered_today(self, conn):
        store.upsert_competition(
            conn, competition(entry_mechanic="web_form", repeat_interval="daily")
        )
        store.record_entry_attempt(
            conn,
            EntryAttempt(
                competition_id="abc123", attempted_at=datetime.now(UTC), outcome="submitted"
            ),
        )

        assert entry_run.select_candidates(conn, _profile()) == []

    def test_orders_by_score_descending(self, conn):
        store.upsert_competition(
            conn,
            competition(
                id="low", canonical_url="https://a.example/x", entry_mechanic="web_form", score=1.0
            ),
        )
        store.upsert_competition(
            conn,
            competition(
                id="high", canonical_url="https://b.example/x", entry_mechanic="web_form", score=9.0
            ),
        )

        candidates = entry_run.select_candidates(conn, _profile())

        assert [c.id for c in candidates] == ["high", "low"]

    def test_respects_max_entries_per_run(self, conn):
        for i in range(3):
            store.upsert_competition(
                conn,
                competition(
                    id=f"c{i}",
                    canonical_url=f"https://domain{i}.example/comp",
                    entry_mechanic="web_form",
                ),
            )

        candidates = entry_run.select_candidates(conn, _profile(max_entries_per_run=2))

        assert len(candidates) == 2

    def test_respects_max_entries_per_domain(self, conn):
        store.upsert_competition(
            conn,
            competition(
                id="a", canonical_url="https://same-domain.example/one", entry_mechanic="web_form"
            ),
        )
        store.upsert_competition(
            conn,
            competition(
                id="b", canonical_url="https://same-domain.example/two", entry_mechanic="web_form"
            ),
        )

        candidates = entry_run.select_candidates(conn, _profile(max_entries_per_domain=1))

        assert len(candidates) == 1


class _FakeMappingClient:
    def __init__(self, mapping: dict[str, str]):
        self._mapping = mapping

    def generate(self, *, system: str, prompt: str) -> str:
        return json.dumps(self._mapping)


PLAIN_FORM_MAP = {
    "email": "#email",
    "terms_accepted": "#terms",
    "marketing_consent": "#marketing",
    "submit": "#submit-button",
}


def test_run_submits_a_real_local_fixture_end_to_end(conn, profile_path, monkeypatch, tmp_path):
    form_url = (FIXTURES / "plain_web_form.html").resolve().as_uri()
    store.upsert_competition(
        conn, competition(canonical_url=form_url, source_urls=[form_url], entry_mechanic="web_form")
    )
    conn.close()  # run() opens its own connection to the same file

    monkeypatch.setattr(
        entry_run, "make_client_from_env", lambda: _FakeMappingClient(PLAIN_FORM_MAP)
    )

    exit_code = entry_run.run(str(profile_path.parent / "test.db"), str(profile_path))

    assert exit_code == 0
    fresh_conn = store.connect(profile_path.parent / "test.db")
    try:
        row = fresh_conn.execute(
            "SELECT outcome, reason FROM entry_attempts WHERE competition_id = 'abc123'"
        ).fetchone()
        assert row is not None, "no entry attempt was recorded at all"
        assert row["outcome"] == "submitted", (
            f"got outcome={row['outcome']!r} reason={row['reason']!r}"
        )
        assert store.get_field_map(fresh_conn, "") == PLAIN_FORM_MAP  # file:// URLs have no host
    finally:
        fresh_conn.close()


def test_run_dry_run_never_marks_a_competition_as_entered(conn, profile_path, monkeypatch):
    form_url = (FIXTURES / "plain_web_form.html").resolve().as_uri()
    store.upsert_competition(
        conn, competition(canonical_url=form_url, source_urls=[form_url], entry_mechanic="web_form")
    )
    conn.close()

    monkeypatch.setattr(
        entry_run, "make_client_from_env", lambda: _FakeMappingClient(PLAIN_FORM_MAP)
    )

    entry_run.run(str(profile_path.parent / "test.db"), str(profile_path), dry_run=True)

    fresh_conn = store.connect(profile_path.parent / "test.db")
    try:
        assert store.has_ever_entered(fresh_conn, "abc123") is False
    finally:
        fresh_conn.close()


def test_run_skips_entirely_without_an_llm_client(conn, profile_path, monkeypatch):
    store.upsert_competition(conn, competition(entry_mechanic="web_form"))
    conn.close()
    monkeypatch.setattr(entry_run, "make_client_from_env", lambda: None)

    exit_code = entry_run.run(str(profile_path.parent / "test.db"), str(profile_path))

    assert exit_code == 0
    fresh_conn = store.connect(profile_path.parent / "test.db")
    try:
        assert store.has_ever_entered(fresh_conn, "abc123") is False
    finally:
        fresh_conn.close()
