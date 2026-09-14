# Competition-Hunter
Competition entry automation

Design rationale: [`docs/design-options.md`](docs/design-options.md).
Build spec: [`docs/implementation-plan.md`](docs/implementation-plan.md).

## Status

Phase 1 (RSS ingest → SQLite → dedupe → static dashboard), phase 2 (LLM
enrichment, EV scoring, entry tracker groundwork) and phase 3 (the local
autofill entry layer) are implemented. Phase 4 (newsletter ingest, wins
ledger) is not built yet.

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
`docs/implementation-plan.md` for why discovery runs in CI while the entry
layer (below) stays local.

```bash
uv run pytest    # unit tests, all against recorded fixtures — no live network
uv run ruff check .
```

## Entering competitions (local only)

The entry layer reads your real details from `profile.toml` and drives a
real browser to fill and submit web-form competitions, so it never runs in
CI — only your own machine. Set it up once:

```bash
cp profile.example.toml profile.toml   # gitignored — never commit this
$EDITOR profile.toml                   # fill in your real name/address/consent
uv run playwright install chromium     # one-time browser download
```

Then run it against the same database the discovery pipeline populates:

```bash
uv run competition-hunter-entry --db competitions.db --profile profile.toml
```

It picks the highest-scoring open, not-yet-entered, auto-routable
(`web_form`, no purchase required, not skill-based) competitions, capped by
`profile.toml`'s `[limits]` (entries per run, entries per domain, and a
randomised delay between entries), and enters each one for real. Add
`--dry-run` to fill in and check every field — including consent
checkboxes — without ever clicking submit, useful for checking how a new
site's form maps before trusting it with a real entry. A CAPTCHA, or a
mandatory marketing-consent checkbox you haven't opted into, aborts that
one entry and queues it for manual review instead of guessing or bypassing
either.
