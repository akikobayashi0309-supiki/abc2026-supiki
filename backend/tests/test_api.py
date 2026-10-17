from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.auth import User, get_current_user
from app.gemini import get_gemini
from app.main import app
from app.media import get_media
from app.store import get_store
from tests.fakes import FakeGemini, FakeMedia, FakeStore


@pytest.fixture
def store():
    return FakeStore()


@pytest.fixture
def client(store):
    app.dependency_overrides[get_current_user] = lambda: User(uid="u1", is_anonymous=True)
    app.dependency_overrides[get_gemini] = FakeGemini
    app.dependency_overrides[get_media] = FakeMedia
    app.dependency_overrides[get_store] = lambda: store
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_healthz():
    assert TestClient(app).get("/api/healthz").json() == {"status": "ok"}


def test_jobs_require_auth():
    res = TestClient(app).post("/api/jobs", json={"videoId": "sintel", "request": "hi there"})
    assert res.status_code == 401


def test_library(client):
    ids = [v["id"] for v in client.get("/api/library").json()]
    assert ids == ["pepper-and-carrot", "tears-of-steel", "sintel"]


def test_create_job_runs_pipeline(client, store):
    res = client.post(
        "/api/jobs", json={"videoId": "tears-of-steel", "request": "Robot fight for Brazil"}
    )
    assert res.status_code == 202
    job = client.get(f"/api/jobs/{res.json()['id']}").json()
    assert job["status"] == "done"
    assert all(s["status"] in ("done", "skipped") for s in job["steps"].values())
    assert set(job["urls"]) == {"clip", "final", "keyframe", "thumbnail"}
    assert job["culture"]["verdict"] == "needs_changes"
    assert job["finalSubtitles"][0]["translated"] == "Revisado"
    assert [j["status"] for j in client.get("/api/jobs").json()] == ["done"]


def test_unknown_video(client):
    res = client.post("/api/jobs", json={"videoId": "nope", "request": "anything"})
    assert res.status_code == 404


def test_one_active_job_per_user(client, store):
    store.create_job("u1", {"status": "running"})
    store.docs["u1"][-1]["updatedAt"] = datetime.now(UTC)
    res = client.post("/api/jobs", json={"videoId": "sintel", "request": "anything"})
    assert res.status_code == 429


def test_other_users_job_is_hidden(client, store):
    job_id = store.create_job("someone-else", {"status": "done"})
    assert client.get(f"/api/jobs/{job_id}").status_code == 404


def test_failed_step_is_marked(client, store, monkeypatch):
    def boom(self, plan, index):
        raise RuntimeError("search exploded")

    monkeypatch.setattr("app.pipeline.Pipeline.search", boom)
    res = client.post("/api/jobs", json={"videoId": "sintel", "request": "anything"})
    job = client.get(f"/api/jobs/{res.json()['id']}").json()
    assert job["status"] == "failed"
    assert job["steps"]["search"]["status"] == "failed"
    assert "search exploded" in job["error"]
