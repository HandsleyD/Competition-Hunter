import json

import pytest

from competition_hunter import store
from competition_hunter.entry.fieldmap import build_field_map, get_or_build_field_map


class _FakeClient:
    def __init__(self, response_text: str):
        self._response_text = response_text
        self.last_prompt: str | None = None

    def generate(self, *, system: str, prompt: str) -> str:
        self.last_prompt = prompt
        return self._response_text


@pytest.fixture
def conn(tmp_path):
    connection = store.connect(tmp_path / "test.db")
    yield connection
    connection.close()


def test_build_field_map_parses_a_well_formed_response():
    payload = {"email": "#email", "submit": "button[type=submit]"}
    client = _FakeClient(json.dumps(payload))

    mapping = build_field_map(client, dom_html="<form></form>")

    assert mapping == payload


def test_build_field_map_passes_the_dom_as_the_prompt():
    client = _FakeClient(json.dumps({}))

    build_field_map(client, dom_html="<form><input id='x'></form>")

    assert client.last_prompt == "<form><input id='x'></form>"


def test_build_field_map_drops_unrecognised_keys():
    payload = {"email": "#email", "not_a_real_field": "#whatever"}
    client = _FakeClient(json.dumps(payload))

    mapping = build_field_map(client, dom_html="<form></form>")

    assert mapping == {"email": "#email"}


def test_build_field_map_drops_non_string_selectors():
    payload = {"email": "#email", "phone": 123}
    client = _FakeClient(json.dumps(payload))

    mapping = build_field_map(client, dom_html="<form></form>")

    assert mapping == {"email": "#email"}


def test_build_field_map_returns_empty_on_invalid_json():
    client = _FakeClient("not json at all")

    assert build_field_map(client, dom_html="<form></form>") == {}


def test_build_field_map_returns_empty_when_response_is_not_an_object():
    client = _FakeClient(json.dumps(["email", "#email"]))

    assert build_field_map(client, dom_html="<form></form>") == {}


def test_get_or_build_field_map_uses_the_cache_without_calling_the_llm(conn):
    store.set_field_map(conn, "example.com", {"email": "#cached"})
    client = _FakeClient(json.dumps({"email": "#fresh"}))

    mapping = get_or_build_field_map(conn, client, "example.com", dom_html="<form></form>")

    assert mapping == {"email": "#cached"}
    assert client.last_prompt is None


def test_get_or_build_field_map_calls_the_llm_and_caches_on_a_miss(conn):
    client = _FakeClient(json.dumps({"email": "#email"}))

    mapping = get_or_build_field_map(conn, client, "example.com", dom_html="<form></form>")

    assert mapping == {"email": "#email"}
    assert store.get_field_map(conn, "example.com") == {"email": "#email"}


def test_get_or_build_field_map_does_not_cache_a_failed_extraction(conn):
    client = _FakeClient("garbage")

    mapping = get_or_build_field_map(conn, client, "example.com", dom_html="<form></form>")

    assert mapping == {}
    assert store.get_field_map(conn, "example.com") is None
