"""SQLite access and migrations.

One file, one schema version at a time — this is a personal-scale project
(tens of thousands of rows at most), so a migration framework would be
overhead. See docs/design-options.md §4.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from competition_hunter.models import Competition, EntryAttempt

SCHEMA = """
CREATE TABLE IF NOT EXISTS competitions (
    id                 TEXT PRIMARY KEY,
    canonical_url      TEXT NOT NULL UNIQUE,
    source_urls        TEXT NOT NULL,   -- JSON list[str]
    source_count       INTEGER NOT NULL,
    title              TEXT NOT NULL,
    description        TEXT NOT NULL DEFAULT '',
    enriched           INTEGER NOT NULL DEFAULT 0,
    promoter           TEXT,
    prize_value_gbp    TEXT,            -- Decimal stored as string
    closes_at          TEXT,            -- ISO 8601
    entry_mechanic     TEXT NOT NULL,
    is_skill_based     INTEGER NOT NULL,
    requires_purchase  INTEGER NOT NULL,
    uk_only            INTEGER NOT NULL,
    min_age            INTEGER,
    repeat_interval    TEXT,
    score              REAL NOT NULL,
    first_seen         TEXT NOT NULL    -- ISO 8601
);

CREATE TABLE IF NOT EXISTS entry_attempts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    competition_id  TEXT NOT NULL REFERENCES competitions(id),
    attempted_at    TEXT NOT NULL,
    outcome         TEXT NOT NULL,
    reason          TEXT
);

CREATE INDEX IF NOT EXISTS idx_entry_attempts_comp_date
    ON entry_attempts (competition_id, date(attempted_at));

CREATE TABLE IF NOT EXISTS field_maps (
    domain      TEXT PRIMARY KEY,
    mapping     TEXT NOT NULL,  -- JSON {profile_key: css_selector}
    updated_at  TEXT NOT NULL
);
"""


# Columns added after the initial schema. New databases get them from SCHEMA
# above; existing ones (e.g. the cached DB a previous discover.yml run left
# behind) get them bolted on here — a lightweight stand-in for a migration
# framework that isn't worth the overhead at this scale.
_ADDED_COLUMNS = {
    "description": "TEXT NOT NULL DEFAULT ''",
    "enriched": "INTEGER NOT NULL DEFAULT 0",
}


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(competitions)")}
    for column, ddl in _ADDED_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE competitions ADD COLUMN {column} {ddl}")
    conn.commit()


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _add_missing_columns(conn)
    return conn


def _row_to_competition(row: sqlite3.Row) -> Competition:
    return Competition(
        id=row["id"],
        canonical_url=row["canonical_url"],
        source_urls=json.loads(row["source_urls"]),
        source_count=row["source_count"],
        title=row["title"],
        description=row["description"],
        enriched=bool(row["enriched"]),
        promoter=row["promoter"],
        prize_value_gbp=Decimal(row["prize_value_gbp"]) if row["prize_value_gbp"] else None,
        closes_at=datetime.fromisoformat(row["closes_at"]) if row["closes_at"] else None,
        entry_mechanic=row["entry_mechanic"],
        is_skill_based=bool(row["is_skill_based"]),
        requires_purchase=bool(row["requires_purchase"]),
        uk_only=bool(row["uk_only"]),
        min_age=row["min_age"],
        repeat_interval=row["repeat_interval"],
        score=row["score"],
        first_seen=datetime.fromisoformat(row["first_seen"]),
    )


def upsert_competition(conn: sqlite3.Connection, competition: Competition) -> Competition:
    """Insert a newly-seen competition, or merge a re-sighting into the existing row.

    Merging matters because the same competition arrives repeatedly from every
    source that lists it — that's the dedupe input for `source_count`
    (design-options.md §5), not something to discard. `first_seen` and the
    accumulated `source_urls` never regress.

    A re-sighting is always freshly normalised, un-enriched data (see
    `pipeline/normalise.py`), so the merge only ever touches listing-derived
    fields (title, description, source_urls). It never overwrites the
    enrichment-owned fields — promoter, prize, closing date, entry mechanic,
    `enriched` itself — which only `mark_enriched` sets, or a re-sighting one
    ingest run after enrichment would wipe them back to "unknown" every time.
    """
    existing = conn.execute("SELECT * FROM competitions WHERE id = ?", (competition.id,)).fetchone()

    if existing is None:
        conn.execute(
            """
            INSERT INTO competitions (
                id, canonical_url, source_urls, source_count, title, description,
                enriched, promoter, prize_value_gbp, closes_at, entry_mechanic,
                is_skill_based, requires_purchase, uk_only, min_age, repeat_interval,
                score, first_seen
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                competition.id,
                competition.canonical_url,
                json.dumps(competition.source_urls),
                competition.source_count,
                competition.title,
                competition.description,
                int(competition.enriched),
                competition.promoter,
                str(competition.prize_value_gbp) if competition.prize_value_gbp else None,
                competition.closes_at.isoformat() if competition.closes_at else None,
                competition.entry_mechanic,
                int(competition.is_skill_based),
                int(competition.requires_purchase),
                int(competition.uk_only),
                competition.min_age,
                competition.repeat_interval,
                competition.score,
                competition.first_seen.isoformat(),
            ),
        )
        conn.commit()
        return competition

    merged_urls = sorted(set(json.loads(existing["source_urls"])) | set(competition.source_urls))
    first_seen = min(datetime.fromisoformat(existing["first_seen"]), competition.first_seen)
    description = competition.description or existing["description"]

    conn.execute(
        """
        UPDATE competitions SET
            source_urls = ?, source_count = ?, title = ?, description = ?, first_seen = ?
        WHERE id = ?
        """,
        (
            json.dumps(merged_urls),
            len(merged_urls),
            competition.title,
            description,
            first_seen.isoformat(),
            competition.id,
        ),
    )
    conn.commit()
    return _row_to_competition(
        conn.execute("SELECT * FROM competitions WHERE id = ?", (competition.id,)).fetchone()
    )


def get_competitions(conn: sqlite3.Connection, order_by: str = "closes_at") -> list[Competition]:
    if order_by not in {"closes_at", "score", "first_seen"}:
        raise ValueError(f"unsupported order_by: {order_by}")
    rows = conn.execute(
        f"SELECT * FROM competitions ORDER BY {order_by} IS NULL, {order_by} ASC"  # noqa: S608
    ).fetchall()
    return [_row_to_competition(row) for row in rows]


def get_unenriched(conn: sqlite3.Connection) -> list[Competition]:
    """Competitions that have never had an enrichment pass. See `mark_enriched`."""
    rows = conn.execute("SELECT * FROM competitions WHERE enriched = 0").fetchall()
    return [_row_to_competition(row) for row in rows]


def mark_enriched(conn: sqlite3.Connection, competition: Competition) -> None:
    """Persist one competition's enrichment result and flag it as done.

    Set regardless of whether the extraction actually found anything, so a
    description the LLM can't get useful fields from is never retried —
    "cache by competition_id, never re-enrich" (implementation-plan.md).
    """
    conn.execute(
        """
        UPDATE competitions SET
            enriched = 1, promoter = ?, prize_value_gbp = ?, closes_at = ?,
            entry_mechanic = ?, is_skill_based = ?, requires_purchase = ?,
            uk_only = ?, min_age = ?, repeat_interval = ?
        WHERE id = ?
        """,
        (
            competition.promoter,
            str(competition.prize_value_gbp) if competition.prize_value_gbp else None,
            competition.closes_at.isoformat() if competition.closes_at else None,
            competition.entry_mechanic,
            int(competition.is_skill_based),
            int(competition.requires_purchase),
            int(competition.uk_only),
            competition.min_age,
            competition.repeat_interval,
            competition.id,
        ),
    )
    conn.commit()


def update_scores(conn: sqlite3.Connection, competitions: Iterable[Competition]) -> None:
    conn.executemany(
        "UPDATE competitions SET score = ? WHERE id = ?",
        [(c.score, c.id) for c in competitions],
    )
    conn.commit()


def record_entry_attempt(conn: sqlite3.Connection, attempt: EntryAttempt) -> None:
    conn.execute(
        "INSERT INTO entry_attempts (competition_id, attempted_at, outcome, reason) "
        "VALUES (?, ?, ?, ?)",
        (attempt.competition_id, attempt.attempted_at.isoformat(), attempt.outcome, attempt.reason),
    )
    conn.commit()


def entered_today(conn: sqlite3.Connection, competition_id: str, today: date | None = None) -> bool:
    """Has this competition already had a submitted entry today?

    This is the query behind "X of Y repeatables done today" (design-options.md
    §5) for `repeat_interval="daily"` comps.
    """
    today = today or datetime.now(UTC).date()
    row = conn.execute(
        "SELECT 1 FROM entry_attempts "
        "WHERE competition_id = ? AND outcome = 'submitted' AND date(attempted_at) = ? LIMIT 1",
        (competition_id, today.isoformat()),
    ).fetchone()
    return row is not None


def repeatable_progress(conn: sqlite3.Connection, today: date | None = None) -> tuple[int, int]:
    """(done, total) daily-repeatable competitions entered today.

    The single highest-value dashboard feature per design-options.md §5 —
    "X of Y repeatables done today" is what spreadsheets do worst.
    """
    today = today or datetime.now(UTC).date()
    total = conn.execute(
        "SELECT COUNT(*) FROM competitions WHERE repeat_interval = 'daily'"
    ).fetchone()[0]
    done = conn.execute(
        """
        SELECT COUNT(DISTINCT competition_id) FROM entry_attempts
        WHERE outcome = 'submitted' AND date(attempted_at) = ?
        AND competition_id IN (SELECT id FROM competitions WHERE repeat_interval = 'daily')
        """,
        (today.isoformat(),),
    ).fetchone()[0]
    return done, total


def upsert_all(conn: sqlite3.Connection, competitions: Iterable[Competition]) -> list[Competition]:
    return [upsert_competition(conn, c) for c in competitions]


def has_ever_entered(conn: sqlite3.Connection, competition_id: str) -> bool:
    """Has this competition ever had a submitted entry, on any day?

    For `repeat_interval` in {None, "once"} this is the guard against
    entering the same one-shot competition twice; daily/weekly/monthly
    repeatables use `entered_today` instead.
    """
    row = conn.execute(
        "SELECT 1 FROM entry_attempts WHERE competition_id = ? AND outcome = 'submitted' LIMIT 1",
        (competition_id,),
    ).fetchone()
    return row is not None


def get_field_map(conn: sqlite3.Connection, domain: str) -> dict[str, str] | None:
    row = conn.execute("SELECT mapping FROM field_maps WHERE domain = ?", (domain,)).fetchone()
    return json.loads(row["mapping"]) if row else None


def set_field_map(conn: sqlite3.Connection, domain: str, mapping: dict[str, str]) -> None:
    conn.execute(
        """
        INSERT INTO field_maps (domain, mapping, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(domain) DO UPDATE SET
            mapping = excluded.mapping, updated_at = excluded.updated_at
        """,
        (domain, json.dumps(mapping), datetime.now(UTC).isoformat()),
    )
    conn.commit()
