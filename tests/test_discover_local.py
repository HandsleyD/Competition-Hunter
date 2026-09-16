import textwrap

import pytest

from competition_hunter import discover_local, store
from tests.factories import raw_listing

MAILBOX_TOML = textwrap.dedent("""\
    [imap]
    host = "imap.mail.yahoo.com"
    email = "me@yahoo.com"
    app_password = "app-password"

    [newsletter]
    since_days = 3
    """)


@pytest.fixture
def mailbox_path(tmp_path):
    path = tmp_path / "mailbox.toml"
    path.write_text(MAILBOX_TOML)
    return path


class _FakeClient:
    def generate(self, *, system: str, prompt: str) -> str:
        return "[]"


class _FakeNewsletterSource:
    name = "newsletter"

    def __init__(self, listings):
        self._listings = listings

    def fetch(self):
        return self._listings


def test_run_falls_back_to_rss_only_without_an_llm_client(tmp_path, mailbox_path, monkeypatch):
    monkeypatch.setattr(discover_local, "make_client_from_env", lambda: None)
    calls = {}

    def fake_cli_run(db_path, output_dir, *, resolve_redirects=True, extra_sources=None):
        calls["extra_sources"] = extra_sources
        return 0

    monkeypatch.setattr(discover_local.cli, "run", fake_cli_run)

    exit_code = discover_local.run(
        str(tmp_path / "db.sqlite"), str(tmp_path / "out"), str(mailbox_path)
    )

    assert exit_code == 0
    assert calls["extra_sources"] is None


def test_run_adds_a_newsletter_source_when_a_client_is_available(
    tmp_path, mailbox_path, monkeypatch
):
    monkeypatch.setattr(discover_local, "make_client_from_env", lambda: _FakeClient())
    captured = {}

    def fake_cli_run(db_path, output_dir, *, resolve_redirects=True, extra_sources=None):
        captured["extra_sources"] = extra_sources
        return 0

    monkeypatch.setattr(discover_local.cli, "run", fake_cli_run)
    monkeypatch.setattr(
        discover_local, "ImapMailbox", lambda host, email, app_password, port: object()
    )

    discover_local.run(str(tmp_path / "db.sqlite"), str(tmp_path / "out"), str(mailbox_path))

    assert len(captured["extra_sources"]) == 1
    assert captured["extra_sources"][0].name == "newsletter"


def test_run_uses_newsletter_since_days_from_mailbox_toml(tmp_path, mailbox_path, monkeypatch):
    monkeypatch.setattr(discover_local, "make_client_from_env", lambda: _FakeClient())
    monkeypatch.setattr(discover_local.cli, "run", lambda *a, **kw: 0)
    monkeypatch.setattr(
        discover_local, "ImapMailbox", lambda host, email, app_password, port: object()
    )
    captured_since_days = {}
    original_source_cls = discover_local.NewsletterSource

    def spy_source(mailbox, client, *, since_days):
        captured_since_days["value"] = since_days
        return original_source_cls(mailbox, client, since_days=since_days)

    monkeypatch.setattr(discover_local, "NewsletterSource", spy_source)

    discover_local.run(str(tmp_path / "db.sqlite"), str(tmp_path / "out"), str(mailbox_path))

    assert captured_since_days["value"] == 3


def test_run_since_days_override_wins_over_the_config_default(tmp_path, mailbox_path, monkeypatch):
    monkeypatch.setattr(discover_local, "make_client_from_env", lambda: _FakeClient())
    monkeypatch.setattr(discover_local.cli, "run", lambda *a, **kw: 0)
    monkeypatch.setattr(
        discover_local, "ImapMailbox", lambda host, email, app_password, port: object()
    )
    captured_since_days = {}
    original_source_cls = discover_local.NewsletterSource

    def spy_source(mailbox, client, *, since_days):
        captured_since_days["value"] = since_days
        return original_source_cls(mailbox, client, since_days=since_days)

    monkeypatch.setattr(discover_local, "NewsletterSource", spy_source)

    discover_local.run(
        str(tmp_path / "db.sqlite"), str(tmp_path / "out"), str(mailbox_path), since_days=99
    )

    assert captured_since_days["value"] == 99


def test_run_end_to_end_with_a_real_cli_run(tmp_path, mailbox_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(discover_local, "make_client_from_env", lambda: _FakeClient())
    monkeypatch.setattr(
        discover_local, "ImapMailbox", lambda host, email, app_password, port: object()
    )
    listing = raw_listing(link="https://example.com/comp", title="Win Big")
    monkeypatch.setattr(
        discover_local, "NewsletterSource", lambda *a, **kw: _FakeNewsletterSource([listing])
    )
    monkeypatch.setattr(discover_local.cli, "default_sources", lambda: [])

    db_path = tmp_path / "db.sqlite"
    out_dir = tmp_path / "out"
    exit_code = discover_local.run(
        str(db_path), str(out_dir), str(mailbox_path), resolve_redirects=False
    )

    assert exit_code == 0
    conn = store.connect(db_path)
    try:
        competitions = store.get_competitions(conn)
    finally:
        conn.close()
    assert [c.title for c in competitions] == ["Win Big"]
