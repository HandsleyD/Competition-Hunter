import json
import textwrap
from datetime import UTC, datetime

import pytest

from competition_hunter import store
from competition_hunter.models import EntryAttempt
from competition_hunter.wins import run as wins_run
from tests.factories import competition, email_message

MAILBOX_TOML = textwrap.dedent("""\
    [imap]
    host = "imap.mail.yahoo.com"
    email = "me@yahoo.com"
    app_password = "app-password"

    [wins]
    since_days = 14
    """)


@pytest.fixture
def mailbox_path(tmp_path):
    path = tmp_path / "mailbox.toml"
    path.write_text(MAILBOX_TOML)
    return path


@pytest.fixture
def conn(tmp_path):
    connection = store.connect(tmp_path / "test.db")
    yield connection
    connection.close()


def test_load_imap_credentials_reads_the_imap_section(mailbox_path):
    credentials = wins_run.load_imap_credentials(mailbox_path)

    assert credentials.host == "imap.mail.yahoo.com"
    assert credentials.email == "me@yahoo.com"
    assert credentials.app_password == "app-password"
    assert credentials.port == 993


def test_load_wins_since_days_reads_the_wins_section(mailbox_path):
    assert wins_run._load_wins_since_days(mailbox_path) == 14


def test_load_wins_since_days_defaults_when_omitted(tmp_path):
    path = tmp_path / "mailbox.toml"
    path.write_text('[imap]\nhost = "h"\nemail = "e"\napp_password = "p"\n')

    assert wins_run._load_wins_since_days(path) == wins_run.DEFAULT_SINCE_DAYS


class _FakeClient:
    def __init__(self, responses: dict[str, dict]):
        self._responses = responses

    def generate(self, *, system: str, prompt: str) -> str:
        for subject, payload in self._responses.items():
            if subject in prompt:
                return json.dumps(payload)
        return json.dumps({"is_win": False})


class _FakeMailbox:
    def __init__(self, emails):
        self._emails = emails
        self.fetch_since_calls = []

    def fetch_since(self, since):
        self.fetch_since_calls.append(since)
        return self._emails


def test_run_records_a_win_matched_to_an_entered_competition(conn, mailbox_path, monkeypatch):
    store.upsert_competition(
        conn, competition(id="hamper", title="Win a Luxury Hamper", score=10.0)
    )
    store.record_entry_attempt(
        conn,
        EntryAttempt(competition_id="hamper", attempted_at=datetime.now(UTC), outcome="submitted"),
    )
    conn.close()

    win_email = email_message(
        message_id="<win@example.com>", subject="You won our hamper giveaway!"
    )
    monkeypatch.setattr(
        wins_run,
        "make_client_from_env",
        lambda: _FakeClient(
            {
                "hamper giveaway": {
                    "is_win": True,
                    "competition_title_guess": "Luxury Hamper Giveaway",
                    "prize_description": "A luxury hamper",
                    "promoter": "Example Ltd",
                    "confidence": 0.85,
                }
            }
        ),
    )
    monkeypatch.setattr(wins_run, "ImapMailbox", lambda *a, **kw: _FakeMailbox([win_email]))

    exit_code = wins_run.run(str(mailbox_path.parent / "test.db"), str(mailbox_path))

    assert exit_code == 0
    fresh_conn = store.connect(mailbox_path.parent / "test.db")
    try:
        wins = store.get_wins(fresh_conn)
        assert len(wins) == 1
        assert wins[0].message_id == "<win@example.com>"
        assert wins[0].competition_id == "hamper"
        assert wins[0].prize_description == "A luxury hamper"
    finally:
        fresh_conn.close()


def test_run_records_a_non_win_without_matching_a_competition(conn, mailbox_path, monkeypatch):
    conn.close()
    newsletter_email = email_message(
        message_id="<newsletter@example.com>", subject="This week's comps"
    )
    monkeypatch.setattr(wins_run, "make_client_from_env", lambda: _FakeClient({}))
    monkeypatch.setattr(wins_run, "ImapMailbox", lambda *a, **kw: _FakeMailbox([newsletter_email]))

    wins_run.run(str(mailbox_path.parent / "test.db"), str(mailbox_path))

    fresh_conn = store.connect(mailbox_path.parent / "test.db")
    try:
        assert store.get_wins(fresh_conn) == []
        assert store.has_processed_email(fresh_conn, "<newsletter@example.com>") is True
    finally:
        fresh_conn.close()


def test_run_never_reclassifies_an_already_processed_email(conn, mailbox_path, monkeypatch):
    conn.close()
    email = email_message(message_id="<seen@example.com>", subject="You won!")

    class _CountingClient(_FakeClient):
        def __init__(self):
            super().__init__({"won": {"is_win": True}})
            self.call_count = 0

        def generate(self, *, system, prompt):
            self.call_count += 1
            return super().generate(system=system, prompt=prompt)

    client = _CountingClient()
    monkeypatch.setattr(wins_run, "make_client_from_env", lambda: client)
    monkeypatch.setattr(wins_run, "ImapMailbox", lambda *a, **kw: _FakeMailbox([email]))

    wins_run.run(str(mailbox_path.parent / "test.db"), str(mailbox_path))
    wins_run.run(str(mailbox_path.parent / "test.db"), str(mailbox_path))

    assert client.call_count == 1


def test_run_skips_entirely_without_an_llm_client(conn, mailbox_path, monkeypatch):
    conn.close()
    monkeypatch.setattr(wins_run, "make_client_from_env", lambda: None)
    mailbox = _FakeMailbox([email_message()])
    monkeypatch.setattr(wins_run, "ImapMailbox", lambda *a, **kw: mailbox)

    exit_code = wins_run.run(str(mailbox_path.parent / "test.db"), str(mailbox_path))

    assert exit_code == 0
    assert mailbox.fetch_since_calls == []


def test_run_continues_after_one_email_fails_to_process(conn, mailbox_path, monkeypatch):
    conn.close()
    good_email = email_message(message_id="<good@example.com>", subject="You won!")
    bad_email = email_message(message_id="<bad@example.com>", subject="Boom")

    class _RaisingClient(_FakeClient):
        def generate(self, *, system, prompt):
            if "Boom" in prompt:
                raise RuntimeError("simulated API failure")
            return super().generate(system=system, prompt=prompt)

    monkeypatch.setattr(
        wins_run, "make_client_from_env", lambda: _RaisingClient({"won": {"is_win": True}})
    )
    monkeypatch.setattr(
        wins_run, "ImapMailbox", lambda *a, **kw: _FakeMailbox([bad_email, good_email])
    )

    exit_code = wins_run.run(str(mailbox_path.parent / "test.db"), str(mailbox_path))

    assert exit_code == 0
    fresh_conn = store.connect(mailbox_path.parent / "test.db")
    try:
        assert store.has_processed_email(fresh_conn, "<good@example.com>") is True
        assert store.has_processed_email(fresh_conn, "<bad@example.com>") is False
    finally:
        fresh_conn.close()


def test_run_uses_since_days_override_over_the_config_default(conn, mailbox_path, monkeypatch):
    conn.close()
    monkeypatch.setattr(wins_run, "make_client_from_env", lambda: _FakeClient({}))
    mailbox = _FakeMailbox([])
    monkeypatch.setattr(wins_run, "ImapMailbox", lambda *a, **kw: mailbox)

    wins_run.run(str(mailbox_path.parent / "test.db"), str(mailbox_path), since_days=1)

    assert len(mailbox.fetch_since_calls) == 1
