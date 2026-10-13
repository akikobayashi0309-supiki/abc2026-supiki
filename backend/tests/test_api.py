from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.auth import User, get_current_user
from app.gemini import get_gemini
from app.main import app
from app.store import get_store


class FakeGemini:
    def generate(self, prompt: str) -> str:
        return f"echo: {prompt}"


class FakeStore:
    def __init__(self) -> None:
        self.docs: list[dict] = []

    def save_generation(self, uid, prompt, output, model):
        doc = {
            "id": str(len(self.docs)),
            "uid": uid,
            "prompt": prompt,
            "output": output,
            "model": model,
            "createdAt": datetime.now(UTC),
        }
        self.docs.append(doc)
        return doc

    def list_generations(self, uid, limit):
        return [d for d in reversed(self.docs) if d["uid"] == uid][:limit]


@pytest.fixture
def client():
    store = FakeStore()
    app.dependency_overrides[get_current_user] = lambda: User(uid="u1", is_anonymous=True)
    app.dependency_overrides[get_gemini] = FakeGemini
    app.dependency_overrides[get_store] = lambda: store
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_healthz():
    assert TestClient(app).get("/api/healthz").json() == {"status": "ok"}


def test_generate_requires_auth():
    res = TestClient(app).post("/api/generate", json={"prompt": "hi"})
    assert res.status_code == 401


def test_generate_and_list(client):
    res = client.post("/api/generate", json={"prompt": "hi"})
    assert res.status_code == 200
    assert res.json()["output"] == "echo: hi"

    history = client.get("/api/generations").json()
    assert [g["prompt"] for g in history] == ["hi"]


def test_generate_rejects_empty_prompt(client):
    assert client.post("/api/generate", json={"prompt": ""}).status_code == 422
