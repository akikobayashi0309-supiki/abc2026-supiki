from types import SimpleNamespace

import pytest
from google.genai import errors

from app import gemini as g


class FakeModels:
    def __init__(self, failures):
        self.failures = failures  # model -> list of status codes to raise first
        self.calls = []

    def generate_content(self, model, contents, config):
        self.calls.append(model)
        queue = self.failures.get(model, [])
        if queue:
            raise errors.APIError(queue.pop(0), {"error": {"message": "x"}})
        return SimpleNamespace(parsed=None, text='{"start": 1, "end": 2, "reason": "r"}')


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(g, "BACKOFF", [0, 0])
    monkeypatch.setattr(g, "_new_client", lambda: None)

    def make(failures):
        gem = g.Gemini()
        gem.client = SimpleNamespace(models=FakeModels(failures))
        return gem

    return make


def test_falls_back_when_latest_model_is_exhausted(client):
    from app.schemas import Selection

    gem = client({"gemini-4-argon": [429, 429, 429]})
    result = gem.structured("gemini-4-argon", ["p"], Selection)
    assert result.end == 2
    assert gem.last_model == "gemini-3.8-flash"


def test_retries_transient_errors_before_falling_back(client):
    from app.schemas import Selection

    gem = client({"gemini-4-argon": [503]})
    gem.structured("gemini-4-argon", ["p"], Selection)
    assert gem.client.models.calls == ["gemini-4-argon", "gemini-4-argon"]
    assert gem.last_model == "gemini-4-argon"


def test_client_errors_are_not_masked(client):
    from app.schemas import Selection

    gem = client({"gemini-4-argon": [400]})
    with pytest.raises(errors.APIError):
        gem.structured("gemini-4-argon", ["p"], Selection)
