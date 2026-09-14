"""Local wins-ledger ingest — reads mailbox.toml, fetches recent emails from
a dedicated comping inbox, classifies each with an LLM, and records any wins
against the competition they were entered for.

    uv run competition-hunter-wins [--db PATH] [--mailbox PATH] [--since-days N]

Local-only per implementation-plan.md's trust split, same as entry/run.py:
mailbox.toml holds a real IMAP password and this never runs in CI.
design-options.md §6: this is the only real feedback signal on whether the
scoring model in pipeline/score.py is any good — a measured hit rate, not a
guess.
"""

from __future__ import annotations

import argparse
import logging
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

from competition_hunter import store
from competition_hunter.llm import make_client_from_env
from competition_hunter.models import EmailMessage, Win
from competition_hunter.wins.classify import classify_email
from competition_hunter.wins.mailbox import ImapMailbox
from competition_hunter.wins.match import find_matching_competition

logger = logging.getLogger("competition_hunter.wins")

DEFAULT_SINCE_DAYS = 30

# Matches pipeline/score.py's rough shape closely enough to see whether
# higher-scored entries actually win more often — the whole point of this
# module. Not tied to score.py's internals, so it never needs updating when
# the weights there are tuned.
SCORE_BANDS: list[tuple[float, float]] = [
    (0.0, 1.0),
    (1.0, 5.0),
    (5.0, 20.0),
    (20.0, float("inf")),
]


class MailboxConfig(BaseModel):
    host: str
    email: str
    app_password: str
    port: int = 993
    since_days: int = DEFAULT_SINCE_DAYS


def load_mailbox_config(path: str | Path) -> MailboxConfig:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    imap = data.get("imap", {})
    since_days = data.get("wins", {}).get("since_days", DEFAULT_SINCE_DAYS)
    return MailboxConfig(**imap, since_days=since_days)


def _process_one(conn, client, email: EmailMessage) -> bool:
    """Classify and record one email. Returns whether it was a win."""
    classification = classify_email(client, email)
    competition = find_matching_competition(conn, classification) if classification.is_win else None
    store.record_win(
        conn,
        Win(
            message_id=email.message_id,
            received_at=email.received_at,
            subject=email.subject,
            sender=email.sender,
            is_win=classification.is_win,
            competition_id=competition.id if competition else None,
            prize_description=classification.prize_description,
            confidence=classification.confidence,
            created_at=datetime.now(UTC),
        ),
    )
    return classification.is_win


def _log_hit_rates(conn) -> None:
    for band in store.hit_rate_by_score_band(conn, SCORE_BANDS):
        lo, hi = band["band"]
        label = f"{lo:g}+" if hi == float("inf") else f"{lo:g}-{hi:g}"
        logger.info("score %s: %d/%d entered competitions won", label, band["won"], band["entered"])


def run(db_path: str, mailbox_path: str, *, since_days: int | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    config = load_mailbox_config(mailbox_path)
    client = make_client_from_env()
    if client is None:
        logger.warning("no LLM client available — cannot classify emails, skipping this run")
        return 0

    mailbox = ImapMailbox(config.host, config.email, config.app_password, port=config.port)
    since = (datetime.now(UTC) - timedelta(days=since_days or config.since_days)).date()

    conn = store.connect(db_path)
    try:
        emails = mailbox.fetch_since(since)
        logger.info("%d emails fetched since %s", len(emails), since)

        processed = won = 0
        for email in emails:
            if store.has_processed_email(conn, email.message_id):
                continue
            try:
                if _process_one(conn, client, email):
                    won += 1
                processed += 1
            except Exception:
                logger.exception("failed to process email %r, skipping", email.subject)

        logger.info("%d new emails processed, %d new wins found", processed, won)
        _log_hit_rates(conn)
    finally:
        conn.close()

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Competition Hunter — wins ledger")
    parser.add_argument("--db", default="competitions.db", help="SQLite database path")
    parser.add_argument("--mailbox", default="mailbox.toml", help="Path to mailbox.toml")
    parser.add_argument(
        "--since-days",
        type=int,
        default=None,
        help="Override mailbox.toml's [wins] since_days for this run",
    )
    args = parser.parse_args()
    return run(args.db, args.mailbox, since_days=args.since_days)


if __name__ == "__main__":
    raise SystemExit(main())
