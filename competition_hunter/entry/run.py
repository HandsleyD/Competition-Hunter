"""Local entry orchestration — reads profile.toml, finds auto-routable
competitions, and enters them.

    uv run competition-hunter-entry [--db PATH] [--profile PATH] [--dry-run]

implementation-plan.md's trust split: this is the *only* thing that ever
reads `profile.toml`, and it never runs in CI — the discovery half
(`cli.py`) never touches this module or the profile data.

Rate-limits hard per profile.toml's `[limits]`: at most `max_entries_per_run`
entries total and `max_entries_per_domain` per domain, with a randomised
delay between entries. Doesn't spoof a User-Agent or otherwise try to look
like anything other than what it is — design-options.md's structural rule
against bot-detection evasion.
"""

from __future__ import annotations

import argparse
import logging
import random
import time
import tomllib
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

from competition_hunter import store
from competition_hunter.entry import router
from competition_hunter.entry.autofill import attempt_entry
from competition_hunter.entry.fieldmap import get_or_build_field_map
from competition_hunter.llm import make_client_from_env
from competition_hunter.models import Competition, EntryAttempt, Profile

logger = logging.getLogger("competition_hunter.entry")

# Grab just the entry form where there is one — keeps the DOM sent to the
# field-mapping LLM call small and cheap, per design-options.md §5's "cheap
# at this volume" framing.
_FORM_OR_BODY_HTML = (
    "document.querySelector('form') ?"
    " document.querySelector('form').outerHTML : document.body.outerHTML"
)


def load_profile(path: str | Path) -> Profile:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    flat = {
        **data.get("identity", {}),
        **data.get("contact", {}),
        **data.get("address", {}),
        "consent": data.get("consent", {}),
        "limits": data.get("limits", {}),
    }
    return Profile(**flat)


def _domain(url: str) -> str:
    return urlsplit(url).netloc


def select_candidates(conn, profile: Profile, now: datetime | None = None) -> list[Competition]:
    """Open, auto-routed, not-yet-entered competitions, highest score
    first, capped by `profile.limits`."""
    now = now or datetime.now(UTC)
    limits = profile.limits
    domain_counts: dict[str, int] = defaultdict(int)
    selected: list[Competition] = []

    all_open = sorted(store.get_competitions(conn), key=lambda c: c.score, reverse=True)
    for competition in all_open:
        if len(selected) >= limits.max_entries_per_run:
            break
        if competition.closes_at is not None and competition.closes_at <= now:
            continue
        if router.route(competition) != "auto":
            continue

        if competition.repeat_interval == "daily":
            already_entered = store.entered_today(conn, competition.id, today=now.date())
        else:
            already_entered = store.has_ever_entered(conn, competition.id)
        if already_entered:
            continue

        domain = _domain(competition.canonical_url)
        if domain_counts[domain] >= limits.max_entries_per_domain:
            continue

        domain_counts[domain] += 1
        selected.append(competition)

    return selected


def _enter_one(
    page, conn, client, competition: Competition, profile: Profile, dry_run: bool
) -> EntryAttempt:
    try:
        page.goto(competition.canonical_url, timeout=30_000)
        domain = _domain(competition.canonical_url)
        dom_html = page.evaluate(_FORM_OR_BODY_HTML)
        field_map = get_or_build_field_map(conn, client, domain, dom_html)
        return attempt_entry(page, competition, profile, field_map, dry_run=dry_run)
    except Exception as exc:
        return EntryAttempt(
            competition_id=competition.id,
            attempted_at=datetime.now(UTC),
            outcome="failed",
            reason=str(exc)[:200],
        )


def run(db_path: str, profile_path: str, *, dry_run: bool = False) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    profile = load_profile(profile_path)
    client = make_client_from_env()
    if client is None:
        logger.warning("no LLM client available — cannot build field maps, skipping this run")
        return 0

    conn = store.connect(db_path)
    try:
        candidates = select_candidates(conn, profile)
        if not candidates:
            logger.info("no auto-eligible competitions to enter this run")
            return 0
        logger.info(
            "%d competitions selected for entry%s", len(candidates), " (dry run)" if dry_run else ""
        )

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                for i, competition in enumerate(candidates):
                    if i > 0:
                        delay = random.uniform(
                            profile.limits.min_delay_seconds, profile.limits.max_delay_seconds
                        )
                        time.sleep(delay)

                    page = browser.new_page()
                    try:
                        attempt = _enter_one(page, conn, client, competition, profile, dry_run)
                    finally:
                        page.close()

                    store.record_entry_attempt(conn, attempt)
                    logger.info("%s: %s", competition.title, attempt.outcome)
            finally:
                browser.close()
    finally:
        conn.close()

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Competition Hunter — local entry layer")
    parser.add_argument("--db", default="competitions.db", help="SQLite database path")
    parser.add_argument("--profile", default="profile.toml", help="Path to profile.toml")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fill and check every field including consent, but never click submit",
    )
    args = parser.parse_args()
    return run(args.db, args.profile, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
