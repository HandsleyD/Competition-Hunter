# Account setup runbook

The two things only you can do. ~20 minutes for the email; the postal address
needs a recommendation read first, because I don't think you want one.

---

## 1. Dedicated comping Gmail

### Why a separate account rather than a `+comps` alias

Three reasons, in order of weight:

1. **The pipeline needs mailbox access.** If newsletters land in your personal
   Gmail, the ingest layer gets read access to your entire personal email. A
   separate account means a compromised token exposes marketing mail and
   nothing else.
2. **Plus-addressing gets rejected.** A meaningful share of entry form
   validators reject `+` in email addresses outright, so you'd silently lose
   comps.
3. **Volume.** Comping generates a genuinely large amount of marketing mail.
   You want it in a different mailbox, not a different label.

### Steps

1. Create the account at `accounts.google.com/signup`. Needs a phone number for
   verification — the same number can verify several accounts.
   - Pick something plausible and neutral (`d.handsley.comps@`, or similar).
     It doesn't need to match your legal name — but the **name you enter on
     entry forms does** need to match your ID, or you lose the prize at claim.
2. Turn on 2-Step Verification. Required for what follows, and this account
   will accumulate enough win notifications to be worth protecting.
3. Subscribe it to the aggregator newsletters:
   [ThePrizeFinder](https://www.theprizefinder.com/),
   [Loquax](https://www.loquax.co.uk/),
   [Competitions Time](https://www.competitions-time.co.uk/),
   [Competition Database](https://www.competitiondatabase.co.uk/).

### API access — use OAuth2, not IMAP

**Google is phasing out app passwords through 2026 in favour of OAuth 2.0.**
Don't build on IMAP + app password; it will break.

1. `console.cloud.google.com` → new project (sign in *as the comping account*).
2. Enable the **Gmail API**.
3. OAuth consent screen → **External**. Add the comping address as a test user.
4. Credentials → OAuth client ID → **Desktop app** → download as
   `credentials.json` into the repo root (gitignored).
5. Scope needed: `gmail.readonly`. Nothing more — the pipeline only reads.
6. First run opens a browser once and writes `token.json`.

> **The gotcha that breaks these pipelines.** While the OAuth app's publishing
> status is **Testing**, refresh tokens expire after **7 days** — your
> unattended ingest will die every week with an auth error that looks like
> nothing you changed. Set publishing status to **In production** to avoid it.
> You'll get an "unverified app" warning at the consent screen; that's expected
> and fine, since you are the only user. Verify the current behaviour at setup
> time — Google moves this around.

---

## 2. Postal address — recommendation: don't

You asked for one, so here are the options and the costs. But I'd push back
before you spend the money, because for comping specifically a separate postal
address **costs you prizes**:

| Problem | Why it bites |
|---|---|
| **Claim deadlines** | Win notices routinely say "claim within 14 days" and are enforced strictly. A mail-forwarding hop eats days of that window. This is the serious one. |
| **Courier delivery** | Many couriers won't deliver to PO Boxes at all, and bulky prizes — appliances, furniture, hampers — simply can't go there. |
| **T&C exclusions** | Some promotions explicitly exclude PO Box and mail-forwarding addresses from eligibility. |
| **ID at claim** | High-value prizes involve an identity check against your address. |
| **Cost** | [Royal Mail PO Box](https://www.mailcoms.co.uk/news/royal-mail-po-box-prices-2026/) runs ~£35–50/month; a virtual office address ~£20/month. That's £240–600/year to recoup before you're ahead. |

### The problem you're actually solving, solved better

The reason to want one is junk mail. But the effective lever is **opting out at
entry time**, not rerouting the mail afterwards — and that's already built into
the design: `profile.toml` defaults `marketing = false` and
`third_party = false`, and the autofill layer is specified to untick those
boxes on every entry. That kills junk at source, for post *and* email, for £0.

Note that the Mailing Preference Service won't help here — it only blocks mail
from companies you have *no* relationship with, and entering a comp creates
one.

### If you want one anyway

Both require photo ID and proof of address (AML rules), a UK bank card, and
sign-up in your own name:

- **Royal Mail PO Box** — ~£35/mo on an annual Collect plan. Post Office
  collection or delivery to your home.
- **Virtual office address** (Hoxton Mix and similar) — from ~£20/mo. A real
  street address, which dodges the PO Box exclusion problem, with scan-and-
  forward.

Tell me which and I'll add it to `profile.toml` and flag the courier-delivery
caveat in the entry router so bulky-prize comps still use your home address.

---

## 3. What happens once these exist

```bash
cp profile.example.toml profile.toml   # fill in, never committed
```

Then the entry layer reads it locally and the newsletter adapter reads the
mailbox. Neither ever touches CI — see the trust split in
[`implementation-plan.md`](implementation-plan.md).
