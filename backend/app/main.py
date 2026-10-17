import logging
from typing import Annotated, Any

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from app.auth import User, get_current_user
from app.config import Settings, get_settings
from app.gemini import Gemini, get_gemini
from app.library import LIBRARY
from app.media import Media, get_media
from app.pipeline import Pipeline, initial_steps
from app.store import Store, get_store

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="api")

CurrentUser = Annotated[User, Depends(get_current_user)]
StoreDep = Annotated[Store, Depends(get_store)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
MediaDep = Annotated[Media, Depends(get_media)]


class JobRequest(BaseModel):
    videoId: str
    request: str = Field(min_length=3, max_length=1000)


@app.get("/api/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/library")
def library(_: CurrentUser) -> list[dict[str, Any]]:
    return [
        {
            "id": v.id,
            "title": v.title,
            "duration": v.duration,
            "synopsis": v.synopsis,
            "credit": v.credit,
        }
        for v in LIBRARY.values()
    ]


@app.post("/api/jobs", status_code=status.HTTP_202_ACCEPTED)
def create_job(
    body: JobRequest,
    user: CurrentUser,
    background: BackgroundTasks,
    store: StoreDep,
    settings: SettingsDep,
    gemini: Annotated[Gemini, Depends(get_gemini)],
    media: MediaDep,
) -> dict[str, str]:
    video = LIBRARY.get(body.videoId)
    if not video:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown video")
    if store.has_active_job(user.uid, settings.stale_job_seconds):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "A job is already running")
    job_id = store.create_job(
        user.uid,
        {
            "videoId": video.id,
            "videoTitle": video.title,
            "request": body.request,
            "status": "queued",
            "steps": initial_steps(),
            "outputs": {},
        },
    )
    pipeline = Pipeline(user.uid, job_id, video, body.request, gemini, media, store, settings)
    background.add_task(pipeline.run)
    return {"id": job_id}


def _summary(job: dict[str, Any]) -> dict[str, Any]:
    keys = ["id", "videoId", "videoTitle", "request", "status", "createdAt"]
    return {k: job.get(k) for k in keys}


@app.get("/api/jobs")
def list_jobs(user: CurrentUser, store: StoreDep, settings: SettingsDep) -> list[dict[str, Any]]:
    return [_summary(job) for job in store.list_jobs(user.uid, settings.history_limit)]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, user: CurrentUser, store: StoreDep, media: MediaDep) -> dict[str, Any]:
    job = store.get_job(user.uid, job_id)
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    job["urls"] = {
        name: media.signed_url(path) for name, path in (job.get("outputs") or {}).items()
    }
    return job
