from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.auth import User, get_current_user
from app.gemini import get_gemini
from app.main import app
from app.media import get_media
from app.runner import get_runner
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
    # Run jobs inline so tests can assert on the finished result.
    app.dependency_overrides[get_runner] = lambda: lambda fn: fn()
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
    assert job["trends"]["sources"][0]["uri"] == "https://example.com"
    assert job["steps"]["plan"]["model"] == "fake-model"
    assert job["culture"]["verdict"] == "needs_changes"
    assert job["finalSubtitles"][0]["translated"] == "Revisado"
    assert [j["status"] for j in client.get("/api/jobs").json()] == ["done"]


def test_unknown_video(client):
    res = client.post("/api/jobs", json={"videoId": "nope", "request": "anything"})
    assert res.status_code == 404


def test_active_job_limit(client, store):
    for _ in range(4):
        store.create_job("u1", {"status": "running"})
    store.docs["u1"][-1]["updatedAt"] = datetime.now(UTC)
    res = client.post("/api/jobs", json={"videoId": "sintel", "request": "anything"})
    assert res.status_code == 429


def test_market_batch_shares_one_scene(client):
    res = client.post(
        "/api/jobs",
        json={"videoId": "sintel", "request": "Dragon clip", "markets": ["Japan", "Brazil"]},
    )
    body = res.json()
    assert len(body["ids"]) == 2 and body["batchId"]
    jobs = client.get(f"/api/batches/{body['batchId']}").json()
    assert [j["market"] for j in jobs] == ["Japan", "Brazil"]
    assert all(j["status"] == "done" for j in jobs)
    assert jobs[0]["clipRange"] == jobs[1]["clipRange"]
    assert jobs[1]["steps"]["search"]["detail"].startswith("Shared scene")


def test_auto_lets_the_agent_pick_the_video(client):
    res = client.post("/api/jobs", json={"videoId": "auto", "request": "Dragon friendship"})
    job = client.get(f"/api/jobs/{res.json()['id']}").json()
    assert job["status"] == "done"
    assert job["videoId"] == "sintel"


def test_upload_flow(client, store):
    res = client.post(
        "/api/uploads", json={"title": "Trailer.mp4", "contentType": "video/mp4", "size": 1000}
    )
    assert res.status_code == 201
    vid = res.json()["id"]
    assert res.json()["uploadUrl"].startswith("https://upload/uploads/u1/")
    assert client.post(f"/api/uploads/{vid}/complete").json() == {"status": "queued"}
    video = store.get_video("u1", vid)
    assert video["status"] == "ready" and video["title"] == "Trailer"
    assert video["duration"] == 120
    mine = [v for v in client.get("/api/library").json() if v["uploaded"]]
    assert mine[0]["id"] == vid
    job = client.post("/api/jobs", json={"videoId": vid, "request": "A teaser for Japan"})
    assert client.get(f"/api/jobs/{job.json()['id']}").json()["status"] == "done"


def test_upload_rejects_bad_type(client):
    res = client.post(
        "/api/uploads", json={"title": "x.gif", "contentType": "image/gif", "size": 10}
    )
    assert res.status_code == 400


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


def test_auto_stops_when_named_title_has_no_footage(client, monkeypatch):
    from app.schemas import Plan, TitleMatch
    from tests import fakes

    plan = fakes.RESPONSES[Plan].model_copy(update={"requested_title": "The Apothecary Diaries"})
    monkeypatch.setitem(fakes.RESPONSES, Plan, plan)
    monkeypatch.setitem(fakes.RESPONSES, TitleMatch, TitleMatch(found=False))
    res = client.post("/api/jobs", json={"videoId": "auto", "request": "薬屋のひとりごと"})
    job = client.get(f"/api/jobs/{res.json()['id']}").json()
    assert job["status"] == "failed"
    assert job["missingFootage"] is True
    assert "The Apothecary Diaries" in job["error"]
    assert job["steps"]["search"]["status"] == "failed"
    assert job["steps"]["trends"]["status"] == "pending"  # Stopped before the slow steps
    assert "outputs" not in job or not job["outputs"]
