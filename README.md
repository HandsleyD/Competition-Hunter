# Competition-Hunter
Competition entry automation

Design rationale: [`docs/design-options.md`](docs/design-options.md).
Build spec: [`docs/implementation-plan.md`](docs/implementation-plan.md).

## Status

Phase 1 (RSS ingest → SQLite → dedupe → static dashboard), phase 2 (LLM
enrichment, EV scoring, entry tracker groundwork), phase 3 (the local
autofill entry layer) and the wins-ledger half of phase 4 are implemented.
Newsletter ingest and selective scrapers are not built yet.

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

## Wins ledger (local only)

design-options.md §6: the only real feedback signal on whether the scoring
model is any good is a measured hit rate — actual wins against what was
entered, broken down by score band. This reads a dedicated inbox's win
notifications over plain IMAP with an app-specific password (not Gmail's
OAuth — Google is phasing app passwords out, but Yahoo/iCloud/Zoho still
issue them), so it never runs in CI either.

Set up a dedicated address you only use for comping — Yahoo Mail is the
easiest: Account Info → Account Security → "Generate app password" (your
normal login password won't work over IMAP once 2-step verification is
on). Then:

```bash
cp mailbox.example.toml mailbox.toml   # gitignored — never commit this
$EDITOR mailbox.toml                   # fill in the address + app password
uv run competition-hunter-wins --db competitions.db --mailbox mailbox.toml
```

Each run fetches recent emails since `mailbox.toml`'s `[wins] since_days`
(or `--since-days` to override), asks an LLM whether each one is a genuine
win notification (vs. a newsletter, receipt, or "you've won!!" scam) rather
than trying to solve this with keyword rules, and — for a real win — fuzzy-
matches its guessed competition title back to something this project
actually entered. Every email is recorded (win or not) so the same one is
never reclassified on a later run, and each run logs a hit-rate breakdown
by score band straight from that data.
