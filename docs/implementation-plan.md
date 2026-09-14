# Implementation plan

Build spec for the implementation session. Rationale for these choices is in
[`design-options.md`](design-options.md) — read §2, §5 and §9 before starting.

**Stack:** Python 3.12+, SQLite, Playwright, Jinja2. `uv` for dependency
management, `ruff` for lint/format, `pytest` for tests.

---

## Trust split — do not violate

| | Host | Holds | Trigger |
|---|---|---|---|
| **Discovery + triage** | GitHub Actions cron | Public competition data only | Scheduled, ~4×/day |
| **Entry** | User's own machine | `profile.toml` — name, address, DOB, phone, email | Local scheduler |

The entry layer's profile **never** enters the repo, CI, or any log line.
`profile.toml` is gitignored; ship `profile.example.toml` instead. The two
halves communicate through the SQLite database, not through shared secrets.

---

## Layout

```
competition_hunter/
  models.py          # pydantic: Competition, EntryAttempt, Profile
  store.py           # SQLite access, migrations
  ingest/
    base.py          # Source protocol: fetch() -> Iterable[RawListing]
    rss.py           # ThePrizeFinder feeds
    newsletter.py    # Gmail -> parsed listings  (phase 2)
    scrape/          # per-site adapters         (phase 4)
  pipeline/
    normalise.py     # RawListing -> Competition
    dedupe.py        # canonical URL + fuzzy match
    enrich.py        # LLM extraction
    score.py         # EV ranking
  dashboard/
    build.py         # -> static HTML
    templates/
  entry/
    router.py        # auto | manual-queue | skip
    autofill.py      # Playwright driver
    fieldmap.py      # LLM DOM field mapping + per-domain cache
tests/
  fixtures/          # recorded feed + HTML samples
.github/workflows/
  discover.yml       # cron ingest -> commit db -> build + publish dashboard
```

---

## Data model

```python
class Competition:
    id: str                     # hash of canonical_url
    canonical_url: str          # redirects followed, tracking params stripped
    source_urls: list[str]      # every aggregator link that resolved here
    source_count: int           # negative ranking signal — see design §5
    title: str
    promoter: str | None
    prize_value_gbp: Decimal | None
    closes_at: datetime | None
    entry_mechanic: Literal["web_form","gleam","viralsweep","rafflecopter",
                            "social","email","postal","unknown"]
    is_skill_based: bool        # tiebreaker question -> strong odds signal
    requires_purchase: bool
    uk_only: bool
    min_age: int | None
    repeat_interval: Literal["once","daily","weekly","monthly"] | None
    score: float
    first_seen: datetime

class EntryAttempt:
    competition_id: str
    attempted_at: datetime
    outcome: Literal["submitted","queued_manual","failed","skipped"]
    reason: str | None
```

`EntryAttempt` is the tracker. For `repeat_interval="daily"` comps the
uniqueness constraint is `(competition_id, date(attempted_at))` — that query is
what drives "X of Y repeatables done today" on the dashboard.

---

## Pipeline notes

**Dedupe** is the load-bearing step. Aggregators wrap entry links in affiliate
redirects, so: follow redirects → strip `utm_*`/`ref`/affiliate params → hash.
Keep `source_count` rather than discarding the duplicates; it's a ranking input.

**Enrich** — one LLM call per new competition over title + description, returning
the structured fields above. Use a Haiku-class model; it's a cheap extraction
task at a few hundred items/day. Cache by `competition_id`, never re-enrich.

**Score** — `(prize_value × P(win)) / effort_minutes`, with `P(win)` proxied per
design §5. `is_skill_based=True` and `source_count==1` are the two strongest
positive signals. Keep the weights in one module-level dict so they're tunable
once the wins ledger gives real feedback.

---

## Entry layer

`router.py` classifies each scored competition:

| Condition | Route |
|---|---|
| `entry_mechanic == "web_form"`, no CAPTCHA detected | **auto-submit** |
| CAPTCHA present | **manual queue** |
| `entry_mechanic in {"social","postal","email"}` | **manual queue** |
| `is_skill_based` (needs a written tiebreaker) | **manual queue** |
| `requires_purchase` | **skip** |

The manual queue surfaces as a dashboard section with deep links. Detect
CAPTCHAs by presence of the usual containers/iframes and abort that entry — do
not attempt to solve, and do not fall back to a solving service.

`fieldmap.py` is the interesting part. Don't write per-site selectors: pass the
form's DOM to a Sonnet-class model and have it return a
`{profile_key: css_selector}` mapping, then cache that per domain in SQLite so
repeat visits cost nothing. Fall back to the LLM when a cached map misses. This
is what generalises to sites never seen before.

Rate-limit hard: no more than one entry per domain per run, randomised delay
between entries, honest User-Agent. Log every attempt to `EntryAttempt`.

---

## Phases

1. **RSS → SQLite → dedupe → dashboard.** ThePrizeFinder feeds only, no
   enrichment, sort by closing date. End-to-end and useful on its own.
2. **Enrich + score + entry tracker.** Where it starts beating doing it by hand.
3. **Entry layer** — router, autofill, field mapping. Local only.
4. **Newsletter ingest, selective scrapers, wins ledger + per-source hit rate.**

## Testing

This environment's egress proxy blocks the comping sites, so **all adapter tests
run against recorded fixtures** in `tests/fixtures/` — commit real feed XML and
form HTML samples. Live integration happens in Actions or locally. Never write a
test that hits a live promoter's entry form.
