from dataclasses import dataclass

from google.genai import errors

from competition_hunter.llm import GeminiClient


@dataclass
class _FakeResponse:
    text: str


class _FakeModelsAPI:
    """Simulates per-model 429s: `exhausted_models` always raise, everything
    else returns a canned response naming which model actually served it."""

    def __init__(self, exhausted_models: set[str]):
        self._exhausted_models = exhausted_models
        self.calls: list[str] = []

    def generate_content(self, *, model: str, contents: str, config):
        self.calls.append(model)
        if model in self._exhausted_models:
            raise errors.ClientError(429, {"error": {"message": "rate limited"}})
        return _FakeResponse(text=f'{{"served_by": "{model}"}}')


class _FakeSDKClient:
    """Stands in for the real google.genai.Client — GeminiClient only ever
    touches `.models.generate_content`."""

    def __init__(self, models_api: _FakeModelsAPI):
        self.models = models_api


def _client_with_fake_models(exhausted_models: set[str], models: list[str] | None = None):
    client = GeminiClient(api_key="fake-key-not-used", models=models)
    fake_models_api = _FakeModelsAPI(exhausted_models)
    client._client = _FakeSDKClient(fake_models_api)
    return client, fake_models_api


def test_generate_uses_the_first_model_when_it_succeeds():
    client, fake = _client_with_fake_models(exhausted_models=set())

    result = client.generate(system="sys", prompt="prompt")

    assert "gemini-3.5-flash-lite" in result
    assert fake.calls == ["gemini-3.5-flash-lite"]


def test_generate_falls_back_to_the_next_model_on_a_429():
    client, fake = _client_with_fake_models(exhausted_models={"gemini-3.5-flash-lite"})

    result = client.generate(system="sys", prompt="prompt")

    assert "gemini-2.5-flash-lite" in result
    assert fake.calls == ["gemini-3.5-flash-lite", "gemini-2.5-flash-lite"]


def test_generate_stays_on_the_fallback_model_for_later_calls():
    client, fake = _client_with_fake_models(exhausted_models={"gemini-3.5-flash-lite"})

    client.generate(system="sys", prompt="first")
    fake.calls.clear()
    client.generate(system="sys", prompt="second")

    # Second call skips straight to the model that already worked - it
    # doesn't re-try the exhausted one every time.
    assert fake.calls == ["gemini-2.5-flash-lite"]


def test_generate_falls_back_through_multiple_exhausted_models():
    client, fake = _client_with_fake_models(
        exhausted_models={"gemini-3.5-flash-lite", "gemini-2.5-flash-lite", "gemini-3-flash"}
    )

    result = client.generate(system="sys", prompt="prompt")

    assert "gemini-2.5-flash" in result
    assert fake.calls == [
        "gemini-3.5-flash-lite",
        "gemini-2.5-flash-lite",
        "gemini-3-flash",
        "gemini-2.5-flash",
    ]


def test_generate_raises_once_every_model_in_the_chain_is_rate_limited():
    all_models = ["a", "b"]
    client, fake = _client_with_fake_models(exhausted_models={"a", "b"}, models=all_models)

    try:
        client.generate(system="sys", prompt="prompt")
        raised = False
    except errors.ClientError as exc:
        raised = True
        assert exc.code == 429

    assert raised
    assert fake.calls == ["a", "b"]


def test_generate_does_not_fall_back_on_a_non_rate_limit_client_error():
    client, fake = _client_with_fake_models(exhausted_models=set())
    fake.generate_content = lambda **kwargs: (_ for _ in ()).throw(
        errors.ClientError(400, {"error": {"message": "bad request"}})
    )

    try:
        client.generate(system="sys", prompt="prompt")
        raised = False
    except errors.ClientError as exc:
        raised = True
        assert exc.code == 400

    assert raised
