import time
from pathlib import Path

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from competition_hunter.entry.autofill import (
    ConsentBlocked,
    apply_consent,
    attempt_entry,
    detect_captcha,
    fill_form,
)
from tests.factories import competition, profile

FIXTURES = Path(__file__).parent / "fixtures" / "forms"

PLAIN_FORM_MAP = {
    "title": "#title",
    "first_name": "#first_name",
    "last_name": "#last_name",
    "dob": "#dob",
    "email": "#email",
    "phone": "#phone",
    "address_line1": "#line1",
    "town": "#town",
    "postcode": "#postcode",
    "marketing_consent": "#marketing",
    "terms_accepted": "#terms",
    "submit": "#submit-button",
}


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception:
            # This sandbox's pre-installed browser build doesn't always match
            # the exact playwright version resolved by `uv add` — fall back
            # to the known-good pinned binary. Never needed on a normal
            # machine with `playwright install` run for the pinned version.
            b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        yield b
        b.close()


@pytest.fixture
def page(browser):
    pg = browser.new_page()
    pg.set_default_timeout(2000)
    yield pg
    pg.close()


def _load(page, filename: str):
    page.goto((FIXTURES / filename).resolve().as_uri())


def test_detect_captcha_is_false_on_a_plain_form(page):
    _load(page, "plain_web_form.html")

    assert detect_captcha(page) is False


def test_detect_captcha_finds_a_recaptcha_widget(page):
    _load(page, "recaptcha_form.html")

    assert detect_captcha(page) is True


def test_fill_form_fills_every_recognised_field(page):
    _load(page, "plain_web_form.html")
    prof = profile(first_name="Ada", last_name="Lovelace", email="ada@example.com")

    fill_form(page, prof, PLAIN_FORM_MAP)

    assert page.input_value("#first_name") == "Ada"
    assert page.input_value("#last_name") == "Lovelace"
    assert page.input_value("#email") == "ada@example.com"
    assert page.input_value("#dob") == "1990-06-15"


def test_fill_form_selects_a_select_option_by_value(page):
    _load(page, "plain_web_form.html")
    prof = profile(title="Mrs")

    fill_form(page, prof, PLAIN_FORM_MAP)

    assert page.locator("#title").input_value() == "Mrs"


def test_fill_form_raises_promptly_when_a_select_option_does_not_exist(page):
    # A form's dropdown might not offer every value a profile can hold.
    # This should fail fast (well under Playwright's ~30s default) rather
    # than hang the whole entry attempt on a missing option.
    _load(page, "plain_web_form.html")
    prof = profile(title="Dr")  # fixture's #title select has no "Dr" option

    started = time.monotonic()
    with pytest.raises(PlaywrightError):
        fill_form(page, prof, PLAIN_FORM_MAP)
    assert time.monotonic() - started < 10


def test_fill_form_skips_fields_not_in_the_map(page):
    _load(page, "plain_web_form.html")

    fill_form(page, profile(), {"email": "#email"})

    assert page.input_value("#first_name") == ""
    assert page.input_value("#email") == "test@example.com"


def test_apply_consent_ticks_terms_and_leaves_marketing_unticked_by_default(page):
    _load(page, "plain_web_form.html")

    apply_consent(page, profile(), PLAIN_FORM_MAP)

    assert page.is_checked("#terms") is True
    assert page.is_checked("#marketing") is False


def test_apply_consent_ticks_marketing_when_profile_opts_in(page):
    _load(page, "plain_web_form.html")
    prof = profile(consent={"marketing": True, "third_party": False, "terms_accepted": True})

    apply_consent(page, prof, PLAIN_FORM_MAP)

    assert page.is_checked("#marketing") is True


def test_apply_consent_unticks_a_form_that_defaults_marketing_to_checked(page):
    _load(page, "plain_web_form.html")
    page.check("#marketing")  # simulate a form that opts you in by default

    apply_consent(page, profile(), PLAIN_FORM_MAP)

    assert page.is_checked("#marketing") is False


def test_apply_consent_raises_when_marketing_is_required_and_not_opted_in(page):
    _load(page, "mandatory_marketing_form.html")
    field_map = {"marketing_consent": "#marketing", "terms_accepted": "#terms"}

    with pytest.raises(ConsentBlocked):
        apply_consent(page, profile(), field_map)


def test_attempt_entry_submits_on_a_plain_form(page):
    _load(page, "plain_web_form.html")
    comp = competition(entry_mechanic="web_form")

    attempt = attempt_entry(page, comp, profile(), PLAIN_FORM_MAP)

    assert attempt.outcome == "submitted"
    assert attempt.competition_id == comp.id
    assert page.get_attribute("body", "data-submitted") == "true"


def test_attempt_entry_dry_run_fills_but_never_clicks_submit(page):
    _load(page, "plain_web_form.html")
    comp = competition(entry_mechanic="web_form")

    attempt = attempt_entry(page, comp, profile(), PLAIN_FORM_MAP, dry_run=True)

    assert attempt.outcome == "dry_run"
    assert page.get_attribute("body", "data-submitted") is None
    assert page.is_checked("#terms") is True  # everything up to submit still ran


def test_attempt_entry_queues_manual_on_captcha(page):
    _load(page, "recaptcha_form.html")
    comp = competition()

    attempt = attempt_entry(page, comp, profile(), {"email": "#email", "submit": "#submit-button"})

    assert attempt.outcome == "queued_manual"
    assert attempt.reason == "captcha_detected"


def test_attempt_entry_queues_manual_when_marketing_is_mandatory(page):
    _load(page, "mandatory_marketing_form.html")
    comp = competition()
    field_map = {
        "email": "#email",
        "marketing_consent": "#marketing",
        "terms_accepted": "#terms",
        "submit": "#submit-button",
    }

    attempt = attempt_entry(page, comp, profile(), field_map)

    assert attempt.outcome == "queued_manual"
    assert "marketing" in attempt.reason


def test_attempt_entry_queues_manual_when_no_submit_selector_was_mapped(page):
    _load(page, "plain_web_form.html")
    comp = competition()

    attempt = attempt_entry(page, comp, profile(), {"email": "#email"})

    assert attempt.outcome == "queued_manual"
    assert attempt.reason == "no submit button identified"


def test_attempt_entry_fails_gracefully_on_a_selector_that_does_not_exist(page):
    _load(page, "plain_web_form.html")
    comp = competition()
    field_map = {"email": "#this-selector-does-not-exist", "submit": "#submit-button"}

    attempt = attempt_entry(page, comp, profile(), field_map)

    assert attempt.outcome == "failed"
    assert attempt.reason is not None
