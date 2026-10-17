import logging
import re
import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from app.auth import User, get_current_user
from app.config import Settings, get_settings
from app.gemini import Gemini, get_gemini
from app.library import LIBRARY, Video, uploaded_video
from app.media import Media, get_media
from app.pipeline import Pipeline, initial_steps
from app.runner import get_runner
from app.store import Store, get_store
from app.uploads import CONTENT_TYPES, process_upload

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="api")

CurrentUser = Annotated[User, Depends(get_current_user)]
StoreDep = Annotated[Store, Depends(get_store)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
MediaDep = Annotated[Media, Depends(get_media)]
GeminiDep = Annotated[Gemini, Depends(get_gemini)]
RunnerDep = Annotated[Callable[[Callable[[], None]], None], Depends(get_runner)]

AUTO = "auto"  # Let the agent pick the video from the whole library


class JobRequest(BaseModel):
    videoId: str
    request: str = Field(min_length=3, max_length=1000)
    # Two or more markets run as a comparison batch on the same scene.
    markets: list[str] = Field(default_factory=list)


class UploadRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    contentType: str
    size: int = Field(gt=0)


@app.get("/api/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


def _user_videos(store: Store, uid: str) -> list[dict[str, Any]]:
    return store.list_videos(uid)


def _resolve(store: Store, uid: str, video_id: str) -> list[Video]:
    """Candidate videos for a job: one video, or every ready video for AUTO."""
    if video_id == AUTO:
        ready = [uploaded_video(d) for d in _user_videos(store, uid) if d.get("status") == "ready"]
        return [*LIBRARY.values(), *ready]
    if video_id in LIBRARY:
        return [LIBRARY[video_id]]
    doc = store.get_video(uid, video_id)
    if not doc or doc.get("status") != "ready":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown or unprocessed video")
    return [uploaded_video(doc)]


@app.get("/api/library")
def library(user: CurrentUser, store: StoreDep, media: MediaDep) -> list[dict[str, Any]]:
    shared = [
        {
            "id": v.id,
            "title": v.title,
            "duration": v.duration,
            "synopsis": v.synopsis,
            "credit": v.credit,
            "status": "ready",
            "posterUrl": f"/posters/{v.id}.jpg",
            "uploaded": False,
        }
        for v in LIBRARY.values()
    ]
    mine = []
    for doc in _user_videos(store, user.uid):
        ready = doc.get("status") in ("indexing", "ready")
        mine.append(
            {
                "id": doc["id"],
                "title": doc.get("title", ""),
                "duration": doc.get("duration", 0),
                "synopsis": doc.get("synopsis", ""),
                "credit": "Uploaded by you",
                "status": doc.get("status"),
                "error": doc.get("error"),
                "posterUrl": media.signed_url(doc["posterPath"]) if ready else None,
                "uploaded": True,
            }
        )
    return [*mine, *shared]


@app.post("/api/uploads", status_code=status.HTTP_201_CREATED)
def create_upload(
    body: UploadRequest, user: CurrentUser, store: StoreDep, media: MediaDep, settings: SettingsDep
) -> dict[str, str]:
    if body.contentType not in CONTENT_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Upload an MP4, MOV or WebM video")
    if body.size > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Max size is {settings.max_upload_mb} MB")
    if len(_user_videos(store, user.uid)) >= settings.max_uploads:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Upload limit reached")
    folder = f"uploads/{user.uid}/{uuid.uuid4().hex}"
    title = re.sub(r"\.(mp4|mov|webm)$", "", body.title, flags=re.IGNORECASE)
    video_id = store.create_video(
        user.uid,
        {
            "title": title,
            "status": "uploading",
            "contentType": body.contentType,
            "size": body.size,
            "sourcePath": f"{folder}/original",
            "path": f"{folder}/video.mp4",
            "posterPath": f"{folder}/poster.jpg",
        },
    )
    url = media.signed_upload_url(f"{folder}/original", body.contentType)
    return {"id": video_id, "uploadUrl": url}


@app.post("/api/uploads/{video_id}/complete", status_code=status.HTTP_202_ACCEPTED)
def complete_upload(
    video_id: str,
    user: CurrentUser,
    store: StoreDep,
    media: MediaDep,
    settings: SettingsDep,
    gemini: GeminiDep,
    run: RunnerDep,
) -> dict[str, str]:
    doc = store.get_video(user.uid, video_id)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload not found")
    if doc.get("status") != "uploading":
        return {"status": doc.get("status", "")}
    size = media.size(doc["sourcePath"])
    if not size:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File was not uploaded")
    if size > settings.max_upload_mb * 1024 * 1024:
        store.update_video(user.uid, video_id, {"status": "failed", "error": "File too large"})
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File too large")
    store.update_video(user.uid, video_id, {"status": "queued"})
    run(lambda: process_upload(user.uid, video_id, gemini, media, store, settings))
    return {"status": "queued"}


@app.post("/api/jobs", status_code=status.HTTP_202_ACCEPTED)
def create_job(
    body: JobRequest,
    user: CurrentUser,
    store: StoreDep,
    settings: SettingsDep,
    gemini: GeminiDep,
    media: MediaDep,
    run: RunnerDep,
) -> dict[str, Any]:
    candidates = _resolve(store, user.uid, body.videoId)
    markets = [m.strip() for m in body.markets if m.strip()][: settings.max_markets]
    runs = len(markets) if len(markets) >= 2 else 1
    active = store.count_active_jobs(user.uid, settings.stale_job_seconds)
    if active + runs > settings.max_active_jobs:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many jobs are running")

    batch_id = uuid.uuid4().hex[:12] if runs > 1 else None
    ids: list[str] = []
    for i in range(runs):
        market = markets[i] if batch_id else None
        prompt = f"{body.request}\nTarget market: {market}" if market else body.request
        first = candidates[0]
        job_id = store.create_job(
            user.uid,
            {
                "videoId": AUTO if len(candidates) > 1 else first.id,
                "videoTitle": "Agent picks the video" if len(candidates) > 1 else first.title,
                "request": body.request,
                "market": market,
                "batchId": batch_id,
                "batchIndex": i,
                "status": "queued",
                "steps": initial_steps(),
                "outputs": {},
            },
        )
        pipeline = Pipeline(
            user.uid,
            job_id,
            candidates,
            prompt,
            # Each job gets its own client and scratch directory.
            gemini if i == 0 else type(gemini)(),
            media if i == 0 else type(media)(),
            store,
            settings,
            leader_id=ids[0] if ids else None,
        )
        run(pipeline.run)
        ids.append(job_id)
    return {"id": ids[0], "ids": ids, "batchId": batch_id}


def _summary(job: dict[str, Any]) -> dict[str, Any]:
    keys = ["id", "videoId", "videoTitle", "request", "market", "batchId", "status", "createdAt"]
    return {k: job.get(k) for k in keys}


def _with_urls(job: dict[str, Any], media: Media) -> dict[str, Any]:
    job["urls"] = {
        name: media.signed_url(path) for name, path in (job.get("outputs") or {}).items()
    }
    return job


@app.get("/api/jobs")
def list_jobs(user: CurrentUser, store: StoreDep, settings: SettingsDep) -> list[dict[str, Any]]:
    return [_summary(job) for job in store.list_jobs(user.uid, settings.history_limit)]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, user: CurrentUser, store: StoreDep, media: MediaDep) -> dict[str, Any]:
    job = store.get_job(user.uid, job_id)
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return _with_urls(job, media)


@app.get("/api/batches/{batch_id}")
def get_batch(
    batch_id: str, user: CurrentUser, store: StoreDep, media: MediaDep
) -> list[dict[str, Any]]:
    jobs = store.list_batch(user.uid, batch_id)
    if not jobs:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Batch not found")
    return [_with_urls(job, media) for job in jobs]
