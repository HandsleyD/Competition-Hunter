"""Playwright-driven entry: fill whatever the field map found, check for a
CAPTCHA first and never solve one, then submit.

design-options.md §9 Decisions: Tier 3 (unattended auto-submit) was chosen
against the tier-2 recommendation, "scoped to plain web forms, single real
identity." The structural, non-configurable rules from that section are
enforced here, at fill-time, not just documented:
- CAPTCHA-gated comps route to a manual queue. Not solved, not bypassed.
- Consent boxes are part of the contract: `terms_accepted` gets ticked,
  marketing/third-party get explicitly set to match the profile — ticked
  only if opted in, unticked otherwise, regardless of the form's own
  default state. A form that makes marketing mandatory routes to the
  manual queue rather than silently opting the user in.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from playwright.sync_api import Page

from competition_hunter.models import Competition, EntryAttempt, Profile

CAPTCHA_SELECTORS = [
    "iframe[src*='recaptcha']",
    "iframe[src*='hcaptcha']",
    ".g-recaptcha",
    "#h-captcha",
    "[data-sitekey]",
]


class ConsentBlocked(Exception):
    """A form requires marketing consent the profile hasn't opted into."""


def detect_captcha(page: Page) -> bool:
    return any(page.locator(selector).count() > 0 for selector in CAPTCHA_SELECTORS)


def _profile_values(profile: Profile) -> dict[str, str]:
    dob = date.fromisoformat(profile.dob)
    return {
        "title": profile.title,
        "first_name": profile.first_name,
        "last_name": profile.last_name,
        "dob": profile.dob,
        "dob_day": str(dob.day),
        "dob_month": str(dob.month),
        "dob_year": str(dob.year),
        "email": profile.email,
        "phone": profile.phone,
        "address_line1": profile.line1,
        "address_line2": profile.line2,
        "town": profile.town,
        "county": profile.county,
        "postcode": profile.postcode,
        "country": profile.country,
    }


def _set_value(page: Page, selector: str, value: str) -> None:
    locator = page.locator(selector).first
    tag = locator.evaluate("el => el.tagName.toLowerCase()")
    if tag == "select":
        # A form may not offer every value a profile can hold (e.g. a form
        # without "Mx" as a title option) — fail fast rather than eating a
        # full default timeout per missing option.
        try:
            locator.select_option(value=value, timeout=3000)
        except Exception:
            locator.select_option(label=value, timeout=3000)
    else:
        locator.fill(value)


def _set_checkbox(page: Page, selector: str, checked: bool) -> None:
    locator = page.locator(selector).first
    if checked:
        locator.check()
    else:
        locator.uncheck()


def fill_form(page: Page, profile: Profile, field_map: dict[str, str]) -> None:
    """Fill whatever the field map identified. A missing key is skipped —
    a partial map is expected and fine, since forms and their fields vary."""
    for key, value in _profile_values(profile).items():
        if selector := field_map.get(key):
            _set_value(page, selector, value)


def apply_consent(page: Page, profile: Profile, field_map: dict[str, str]) -> None:
    """Raises ConsentBlocked rather than ticking a mandatory marketing box
    the profile didn't opt into."""
    if selector := field_map.get("marketing_consent"):
        locator = page.locator(selector).first
        if locator.get_attribute("required") is not None and not profile.consent.marketing:
            raise ConsentBlocked("marketing consent is required by this form")
        _set_checkbox(page, selector, profile.consent.marketing)

    if selector := field_map.get("third_party_consent"):
        _set_checkbox(page, selector, profile.consent.third_party)

    if selector := field_map.get("terms_accepted"):
        _set_checkbox(page, selector, profile.consent.terms_accepted)


def submit(page: Page, field_map: dict[str, str]) -> None:
    page.locator(field_map["submit"]).first.click()


def attempt_entry(
    page: Page,
    competition: Competition,
    profile: Profile,
    field_map: dict[str, str],
    *,
    dry_run: bool = False,
) -> EntryAttempt:
    """One entry attempt end to end. Never raises for an outcome a human is
    meant to review (a CAPTCHA, blocked consent, no submit button found) or
    for a fill/submit failure against a page that didn't match the cached
    field map — those become a `queued_manual` or `failed` EntryAttempt
    instead of crashing the run for every other competition in the batch.

    `dry_run=True` does everything except the final submit click, returning
    outcome "dry_run" instead of "submitted" — lets a real entry, including
    the live field map, consent handling and CAPTCHA check, be verified
    against a real site without it ever counting as an actual entry.
    """
    now = datetime.now(UTC)

    if detect_captcha(page):
        return EntryAttempt(
            competition_id=competition.id,
            attempted_at=now,
            outcome="queued_manual",
            reason="captcha_detected",
        )

    try:
        apply_consent(page, profile, field_map)
    except ConsentBlocked as exc:
        return EntryAttempt(
            competition_id=competition.id,
            attempted_at=now,
            outcome="queued_manual",
            reason=str(exc),
        )

    if "submit" not in field_map:
        return EntryAttempt(
            competition_id=competition.id,
            attempted_at=now,
            outcome="queued_manual",
            reason="no submit button identified",
        )

    try:
        fill_form(page, profile, field_map)
        if not dry_run:
            submit(page, field_map)
    except Exception as exc:  # a bad selector on this one page shouldn't sink the run
        return EntryAttempt(
            competition_id=competition.id, attempted_at=now, outcome="failed", reason=str(exc)[:200]
        )

    outcome = "dry_run" if dry_run else "submitted"
    return EntryAttempt(competition_id=competition.id, attempted_at=now, outcome=outcome)
