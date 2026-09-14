"""LLM DOM field mapping, cached per domain.

design-options.md §7 (tier 2): don't write per-site selectors. Give an LLM
the entry form's DOM and have it return `{profile_key: css_selector}`, cache
that per domain in SQLite so repeat visits cost nothing, and fall back to
the LLM only when the cache misses. This is what generalises to sites the
project has never seen before instead of a decade-old comping tool's brittle
selector list.

Reuses `pipeline.enrich.LLMClient` — same "answer a prompt with text" shape,
so this needs no provider-specific code of its own.
"""

from __future__ import annotations

import json
import logging
import sqlite3

from competition_hunter import store
from competition_hunter.pipeline.enrich import LLMClient

logger = logging.getLogger(__name__)

# Every field the autofill layer knows how to act on. dob is offered both as
# a single field and as split day/month/year selects, since entry forms do
# both — autofill.py fills whichever the map actually found.
PROFILE_FIELD_KEYS = frozenset(
    {
        "title",
        "first_name",
        "last_name",
        "dob",
        "dob_day",
        "dob_month",
        "dob_year",
        "email",
        "phone",
        "address_line1",
        "address_line2",
        "town",
        "county",
        "postcode",
        "country",
        "marketing_consent",
        "third_party_consent",
        "terms_accepted",
        "submit",
    }
)

SYSTEM_PROMPT = f"""\
You map a competition entry form's HTML to the profile fields a form-filler \
needs to act on. Given the form's DOM, respond with a single JSON object \
only - no prose, no markdown fences - mapping profile field names to CSS \
selectors that uniquely identify the matching input/select/checkbox/button \
in the page.

Only use these field names, and only include a field if you can identify it \
with confidence: {sorted(PROFILE_FIELD_KEYS)}

- "dob" is a single date input; if the form instead has separate day/month/
  year selects, use "dob_day"/"dob_month"/"dob_year" instead, not "dob".
- "marketing_consent" and "third_party_consent" are checkboxes for opting
  into promotional contact, not the terms-and-conditions checkbox.
- "terms_accepted" is the checkbox that must be ticked to be allowed to
  enter at all.
- "submit" is the button that submits the entry.

Every selector must be something a browser automation tool could click or
fill directly. Omit any field the form doesn't have."""


def build_field_map(client: LLMClient, dom_html: str) -> dict[str, str]:
    """One LLM call, mapping a form's DOM to CSS selectors.

    Returns an empty mapping (rather than raising) on a malformed response —
    a single bad extraction shouldn't sink the entry run, and this domain
    simply gets retried on the next attempt since a failed map is never
    cached (see `get_or_build_field_map`).
    """
    try:
        text = client.generate(system=SYSTEM_PROMPT, prompt=dom_html)
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("fieldmap: could not parse a response: %s", exc)
        return {}

    if not isinstance(raw, dict):
        logger.warning("fieldmap: response was not a JSON object")
        return {}

    return {
        key: selector
        for key, selector in raw.items()
        if key in PROFILE_FIELD_KEYS and isinstance(selector, str) and selector
    }


def get_or_build_field_map(
    conn: sqlite3.Connection, client: LLMClient, domain: str, dom_html: str
) -> dict[str, str]:
    cached = store.get_field_map(conn, domain)
    if cached is not None:
        return cached

    mapping = build_field_map(client, dom_html)
    if mapping:
        store.set_field_map(conn, domain, mapping)
    return mapping
