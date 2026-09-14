import json

from competition_hunter.wins.classify import WinClassification, classify_email
from tests.factories import email_message


class _FakeClient:
    def __init__(self, response: str):
        self._response = response
        self.calls: list[tuple[str, str]] = []

    def generate(self, *, system: str, prompt: str) -> str:
        self.calls.append((system, prompt))
        return self._response


def test_classify_email_parses_a_win():
    payload = {
        "is_win": True,
        "competition_title_guess": "Win a Luxury Hamper",
        "prize_description": "A luxury hamper",
        "promoter": "Example Ltd",
        "confidence": 0.9,
    }
    client = _FakeClient(json.dumps(payload))

    result = classify_email(client, email_message())

    assert result == WinClassification(**payload)


def test_classify_email_defaults_to_not_a_win_on_malformed_json():
    client = _FakeClient("not json")

    result = classify_email(client, email_message())

    assert result == WinClassification()


def test_classify_email_defaults_to_not_a_win_on_a_schema_mismatch():
    client = _FakeClient(json.dumps({"is_win": "maybe"}))

    result = classify_email(client, email_message())

    assert result == WinClassification()


def test_classify_email_includes_subject_and_sender_in_the_prompt():
    client = _FakeClient(json.dumps({"is_win": False}))
    email = email_message(subject="Great news!", sender="wins@example.com", body_text="You won!")

    classify_email(client, email)

    _, prompt = client.calls[0]
    assert "Great news!" in prompt
    assert "wins@example.com" in prompt
    assert "You won!" in prompt


def test_classify_email_truncates_a_very_long_body():
    client = _FakeClient(json.dumps({"is_win": False}))
    email = email_message(body_text="x" * 10_000)

    classify_email(client, email)

    _, prompt = client.calls[0]
    assert len(prompt) < 5000
