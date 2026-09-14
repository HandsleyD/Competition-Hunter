"""Discovery + triage pipeline: RSS ingest -> SQLite -> dedupe -> enrich ->
score -> dashboard.

    uv run competition-hunter [--db PATH] [--out DIR]

This is what .github/workflows/discover.yml runs on a schedule. It only ever
touches public data — the trust split in docs/implementation-plan.md keeps
profile.toml and the entry layer off this path entirely.

Enrichment needs `ANTHROPIC_API_KEY` in the environment; without it, this
still runs end-to-end (competitions just stay unenriched, and score with
default assumptions) rather than failing outright — useful for local dev.
"""

from __future__ import annotations

import argparse
import logging
import os

import anthropic

from competition_hunter import store
from competition_hunter.dashboard.build import build as build_dashboard
from competition_hunter.ingest.rss import default_sources
from competition_hunter.pipeline.enrich import enrich_all
from competition_hunter.pipeline.normalise import normalise_and_dedupe
from competition_hunter.pipeline.score import score_all

logger = logging.getLogger("competition_hunter")


def _make_llm_client() -> anthropic.Anthropic | None:
    # Checked explicitly rather than left to the SDK: newer anthropic clients
    # defer auth validation to request time, so constructing one without a
    # key doesn't raise until the first real API call.
    if not os.environ.get("ANTHROPIC_API_KEY"):
        logger.warning("ANTHROPIC_API_KEY not set — skipping enrichment this run")
        return None
    return anthropic.Anthropic()


def run(db_path: str, output_dir: str, *, resolve_redirects: bool = True) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    listings = []
    for source in default_sources():
        try:
            fetched = list(source.fetch())
        except Exception:
            logger.exception("source %s failed, skipping", source.name)
            continue
        logger.info("%s: %d listings", source.name, len(fetched))
        listings.extend(fetched)

    competitions = normalise_and_dedupe(listings, resolve_redirects=resolve_redirects)
    logger.info("%d listings deduped to %d competitions", len(listings), len(competitions))

    conn = store.connect(db_path)
    try:
        stored = store.upsert_all(conn, competitions)

        unenriched = store.get_unenriched(conn)
        client = _make_llm_client() if unenriched else None
        if client is not None:
            try:
                enriched = enrich_all(client, unenriched)
            except Exception:
                # A systemic failure (bad key, API outage) — leave everything
                # unenriched for the next run rather than caching a bad result.
                logger.exception(
                    "enrichment pass failed, leaving %d competitions unenriched", len(unenriched)
                )
            else:
                for competition in enriched:
                    store.mark_enriched(conn, competition)
                logger.info("enriched %d competitions", len(enriched))

        all_open = store.get_competitions(conn)
        scored = score_all(all_open)
        store.update_scores(conn, scored)

        repeatables_done, repeatables_total = store.repeatable_progress(conn)
    finally:
        conn.close()

    index_path = build_dashboard(
        scored, output_dir, repeatables=(repeatables_done, repeatables_total)
    )
    logger.info(
        "dashboard written to %s (%d new/updated of %d total)",
        index_path,
        len(stored),
        len(scored),
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Competition Hunter — discovery and triage")
    parser.add_argument("--db", default="competitions.db", help="SQLite database path")
    parser.add_argument("--out", default="dashboard/out", help="Dashboard output directory")
    parser.add_argument(
        "--no-resolve-redirects",
        action="store_true",
        help="Skip following redirects when canonicalizing URLs (faster, less accurate)",
    )
    args = parser.parse_args()
    return run(args.db, args.out, resolve_redirects=not args.no_resolve_redirects)


if __name__ == "__main__":
    raise SystemExit(main())
