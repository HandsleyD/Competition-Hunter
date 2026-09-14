# Competition-Hunter
Competition entry automation

Design rationale: [`docs/design-options.md`](docs/design-options.md).
Build spec: [`docs/implementation-plan.md`](docs/implementation-plan.md).

## Status

Phase 1 (RSS ingest → SQLite → dedupe → static dashboard) is implemented.
Phases 2–4 (enrichment, scoring, entry tracker, autofill) are not built yet.

## Running it

```bash
uv sync
uv run competition-hunter --db competitions.db --out dashboard/out
```

This fetches the configured RSS feeds, dedupes them against the SQLite
database, and writes `dashboard/out/index.html`. In production this runs on
a schedule via [`.github/workflows/discover.yml`](.github/workflows/discover.yml),
which publishes the dashboard to GitHub Pages — see the trust split in
`docs/implementation-plan.md` for why discovery runs in CI while the (not yet
built) entry layer stays local.

```bash
uv run pytest    # unit tests, all against recorded fixtures — no live network
uv run ruff check .
```
