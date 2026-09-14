from competition_hunter import cli
from tests.factories import raw_listing


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


def test_run_skips_failing_source_without_crashing(tmp_path, monkeypatch):
    class _BrokenSource:
        name = "broken"

        def fetch(self):
            raise RuntimeError("network is down")

    monkeypatch.setattr(cli, "default_sources", lambda: [_BrokenSource()])

    exit_code = cli.run(str(tmp_path / "db.sqlite"), str(tmp_path / "out"), resolve_redirects=False)

    assert exit_code == 0
    assert (tmp_path / "out" / "index.html").exists()
