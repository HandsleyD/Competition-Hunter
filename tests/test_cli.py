import json

import pytest

from competition_hunter import cli, store
from tests.factories import raw_listing


@pytest.fixture(autouse=True)
def _no_llm_key_by_default(monkeypatch):
    # Enrichment must never fire in a test unless the test explicitly wants
    # it — otherwise a missing monkeypatch would try to hit the real API.
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


class _FakeSource:
    def __init__(self, name, listings):
        self.name = name
        self._listings = listings

    def fetch(self):
        return self._listings


def test_run_ingests_dedupes_and_builds_dashboard(tmp_path, monkeypatch):
    sources = [
        _FakeSource(
            "fake-new",
            [raw_listing(source_name="fake-new", link="https://example.com/comp", title="Win Big")],
        ),
        _FakeSource(
            "fake-closing-soon",
            [
                raw_listing(
                    source_name="fake-closing-soon",
                    link="https://example.com/comp?utm_source=cs",
                    title="Win Big",
                )
            ],
        ),
    ]
    monkeypatch.setattr(cli, "default_sources", lambda: sources)

    db_path = tmp_path / "competitions.db"
    out_dir = tmp_path / "out"

    exit_code = cli.run(str(db_path), str(out_dir), resolve_redirects=False)

    assert exit_code == 0
    assert db_path.exists()
    assert (out_dir / "index.html").exists()
    assert "Win Big" in (out_dir / "index.html").read_text()


def test_run_includes_extra_sources_alongside_the_default_ones(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "default_sources", lambda: [])
    extra = _FakeSource(
        "newsletter", [raw_listing(link="https://example.com/comp", title="From Newsletter")]
    )

    exit_code = cli.run(
        str(tmp_path / "db.sqlite"),
        str(tmp_path / "out"),
        resolve_redirects=False,
        extra_sources=[extra],
    )

    assert exit_code == 0
    assert "From Newsletter" in (tmp_path / "out" / "index.html").read_text()


def test_run_skips_failing_source_without_crashing(tmp_path, monkeypatch):
    class _BrokenSource:
        name = "broken"

        def fetch(self):
            raise RuntimeError("network is down")

    monkeypatch.setattr(cli, "default_sources", lambda: [_BrokenSource()])

    exit_code = cli.run(str(tmp_path / "db.sqlite"), str(tmp_path / "out"), resolve_redirects=False)

    assert exit_code == 0
    assert (tmp_path / "out" / "index.html").exists()


def test_run_skips_enrichment_without_api_key(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cli,
        "default_sources",
        lambda: [
            _FakeSource(
                "fake",
                [
                    raw_listing(
                        link="https://example.com/comp",
                        title="Win Big",
                        description="A prize draw.",
                    )
                ],
            )
        ],
    )

    db_path = tmp_path / "competitions.db"
    cli.run(str(db_path), str(tmp_path / "out"), resolve_redirects=False)

    conn = store.connect(db_path)
    try:
        assert len(store.get_unenriched(conn)) == 1
    finally:
        conn.close()


class _FakeGeminiClient:
    def __init__(self, payload: dict):
        self._payload = payload

    def generate(self, *, system: str, prompt: str) -> str:
        return json.dumps(self._payload)


def test_run_enriches_and_scores_when_api_key_present(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        cli,
        "default_sources",
        lambda: [
            _FakeSource(
                "fake",
                [
                    raw_listing(
                        link="https://example.com/comp",
                        title="Win Big",
                        description="Answer a skill question to enter. UK only.",
                    )
                ],
            )
        ],
    )
    payload = {
        "promoter": "Acme Ltd",
        "prize_value_gbp": 500,
        "closes_at": None,
        "entry_mechanic": "web_form",
        "is_skill_based": True,
        "requires_purchase": False,
        "uk_only": True,
        "min_age": 18,
        "repeat_interval": None,
    }
    monkeypatch.setattr(cli, "make_client_from_env", lambda: _FakeGeminiClient(payload))

    db_path = tmp_path / "competitions.db"
    out_dir = tmp_path / "out"
    cli.run(str(db_path), str(out_dir), resolve_redirects=False)

    conn = store.connect(db_path)
    try:
        competitions = store.get_competitions(conn)
        assert store.get_unenriched(conn) == []
    finally:
        conn.close()

    assert len(competitions) == 1
    comp = competitions[0]
    assert comp.promoter == "Acme Ltd"
    assert comp.is_skill_based is True
    assert comp.score > 0

    html = (out_dir / "index.html").read_text()
    assert "Acme Ltd" in html
    assert "£500" in html
