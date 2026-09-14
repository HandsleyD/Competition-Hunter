import json
from datetime import UTC, date, datetime
from decimal import Decimal

from competition_hunter.pipeline.enrich import apply_extraction, enrich_all, extract
from tests.factories import competition


class _FakeClient:
    def __init__(self, response_text: str):
        self._response_text = response_text
        self.last_call: dict | None = None

    def generate(self, *, system: str, prompt: str) -> str:
        self.last_call = {"system": system, "prompt": prompt}
        return self._response_text


VALID_PAYLOAD = {
    "promoter": "Acme Ltd",
    "prize_value_gbp": 250.0,
    "closes_at": "2026-12-25",
    "entry_mechanic": "web_form",
    "is_skill_based": True,
    "requires_purchase": False,
    "uk_only": True,
    "min_age": 18,
    "repeat_interval": None,
}


def test_extract_parses_a_well_formed_response():
    client = _FakeClient(json.dumps(VALID_PAYLOAD))

    extraction = extract(client, title="Win a Prize", description="Answer this skill question.")

    assert extraction is not None
    assert extraction.promoter == "Acme Ltd"
    assert extraction.prize_value_gbp == 250.0
    assert extraction.closes_at == date(2026, 12, 25)
    assert extraction.is_skill_based is True


def test_extract_passes_title_and_description_to_the_model():
    client = _FakeClient(json.dumps(VALID_PAYLOAD))

    extract(client, title="Win a Prize", description="Some details here.")

    assert "Win a Prize" in client.last_call["prompt"]
    assert "Some details here." in client.last_call["prompt"]


def test_extract_returns_none_on_invalid_json():
    client = _FakeClient("not json at all")

    assert extract(client, title="Win a Prize", description="") is None


def test_extract_returns_none_on_schema_violation():
    client = _FakeClient(json.dumps({"entry_mechanic": "not-a-real-mechanic"}))

    assert extract(client, title="Win a Prize", description="") is None


def test_apply_extraction_updates_the_competition_fields():
    base = competition(title="Win a Prize")
    client = _FakeClient(json.dumps(VALID_PAYLOAD))
    extraction = extract(client, title=base.title, description=base.description)

    updated = apply_extraction(base, extraction)

    assert updated.id == base.id  # identity fields untouched
    assert updated.promoter == "Acme Ltd"
    assert updated.prize_value_gbp == Decimal("250.0")
    assert updated.closes_at == datetime(2026, 12, 25, tzinfo=UTC)
    assert updated.entry_mechanic == "web_form"


def test_enrich_all_leaves_a_competition_unchanged_on_parse_failure():
    client = _FakeClient("garbage")
    base = competition(title="Mystery Prize")

    results = enrich_all(client, [base])

    assert results == [base]


def test_enrich_all_returns_one_result_per_input():
    client = _FakeClient(json.dumps(VALID_PAYLOAD))
    competitions = [competition(id="a"), competition(id="b")]

    results = enrich_all(client, competitions)

    assert len(results) == 2
    assert {c.promoter for c in results} == {"Acme Ltd"}
