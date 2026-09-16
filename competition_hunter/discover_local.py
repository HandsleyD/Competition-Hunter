"""Local discovery run — everything cli.py's CI-safe run does, plus the
newsletter inbox on top.

    uv run competition-hunter-discover-local \
        [--db PATH] [--out DIR] [--mailbox PATH] [--since-days N]

Local-only per implementation-plan.md's trust split, same as entry/run.py
and wins/run.py: mailbox.toml holds a real IMAP password, so unlike
cli.py this never runs in CI — discover.yml keeps calling cli.main()
unchanged, RSS feeds only.
"""

from __future__ import annotations

import argparse
import logging
import tomllib
from pathlib import Path

from competition_hunter import cli
from competition_hunter.ingest.newsletter import NewsletterSource
from competition_hunter.llm import make_client_from_env
from competition_hunter.mailbox import ImapMailbox, load_imap_credentials

logger = logging.getLogger("competition_hunter.discover_local")

DEFAULT_SINCE_DAYS = 7


def _load_newsletter_since_days(path: str | Path) -> int:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return data.get("newsletter", {}).get("since_days", DEFAULT_SINCE_DAYS)


def run(
    db_path: str,
    output_dir: str,
    mailbox_path: str,
    *,
    since_days: int | None = None,
    resolve_redirects: bool = True,
) -> int:
    client = make_client_from_env()
    if client is None:
        logger.warning("no LLM client available — newsletter ingest needs one to extract listings")
        return cli.run(db_path, output_dir, resolve_redirects=resolve_redirects)

    credentials = load_imap_credentials(mailbox_path)
    mailbox = ImapMailbox(
        credentials.host, credentials.email, credentials.app_password, port=credentials.port
    )
    newsletter_source = NewsletterSource(
        mailbox, client, since_days=since_days or _load_newsletter_since_days(mailbox_path)
    )

    return cli.run(
        db_path, output_dir, resolve_redirects=resolve_redirects, extra_sources=[newsletter_source]
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Competition Hunter — discovery including the newsletter inbox"
    )
    parser.add_argument("--db", default="competitions.db", help="SQLite database path")
    parser.add_argument("--out", default="dashboard/out", help="Dashboard output directory")
    parser.add_argument("--mailbox", default="mailbox.toml", help="Path to mailbox.toml")
    parser.add_argument(
        "--since-days",
        type=int,
        default=None,
        help="Override mailbox.toml's [newsletter] since_days for this run",
    )
    parser.add_argument(
        "--no-resolve-redirects",
        action="store_true",
        help="Skip following redirects when canonicalizing URLs (faster, less accurate)",
    )
    args = parser.parse_args()
    return run(
        args.db,
        args.out,
        args.mailbox,
        since_days=args.since_days,
        resolve_redirects=not args.no_resolve_redirects,
    )


if __name__ == "__main__":
    raise SystemExit(main())
