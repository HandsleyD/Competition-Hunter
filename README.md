# Competition-Hunter
Competition entry automation

Design rationale: [`docs/design-options.md`](docs/design-options.md).
Build spec: [`docs/implementation-plan.md`](docs/implementation-plan.md).

## Status

Phase 1 (RSS ingest → SQLite → dedupe → static dashboard) and phase 2
(LLM enrichment, EV scoring, entry tracker groundwork) are implemented.
Phases 3–4 (autofill entry layer, newsletter ingest, wins ledger) are not
built yet.

## Running it

```bash
uv sync
export GEMINI_API_KEY=...   # optional — enrichment is skipped without it; free tier at aistudio.google.com
uv run competition-hunter --db competitions.db --out dashboard/out
```

This fetches the configured RSS feeds, dedupes them against the SQLite
database, enriches any new competitions with an LLM call via Gemini
(title/description → promoter, prize value, closing date, entry mechanic,
restrictions — chosen over Anthropic for its no-payment-method free tier),
scores them by £-per-minute-of-effort, and writes `dashboard/out/index.html` ranked
highest score first. In production this runs on a schedule via
[`.github/workflows/discover.yml`](.github/workflows/discover.yml), which
publishes the dashboard to GitHub Pages — see the trust split in
`docs/implementation-plan.md` for why discovery runs in CI while the (not yet
built) entry layer stays local.

```bash
uv run pytest    # unit tests, all against recorded fixtures — no live network
uv run ruff check .
```
