from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

from google.cloud import firestore

from app.config import get_settings


@lru_cache
def _db() -> firestore.Client:
    return firestore.Client(project=get_settings().google_cloud_project or None)


def _jobs(uid: str) -> firestore.CollectionReference:
    # Per-user subcollection: ordering by createdAt needs no composite index.
    return _db().collection("users").document(uid).collection("jobs")


def _videos(uid: str) -> firestore.CollectionReference:
    return _db().collection("users").document(uid).collection("videos")


def now() -> datetime:
    return datetime.now(UTC)


class Store:
    def create_job(self, uid: str, data: dict[str, Any]) -> str:
        ref = _jobs(uid).document()
        ref.set({**data, "createdAt": now(), "updatedAt": now()})
        return ref.id

    def update_job(self, uid: str, job_id: str, data: dict[str, Any]) -> None:
        _jobs(uid).document(job_id).update({**data, "updatedAt": now()})

    def get_job(self, uid: str, job_id: str) -> dict[str, Any] | None:
        snap = _jobs(uid).document(job_id).get()
        return {"id": snap.id, **snap.to_dict()} if snap.exists else None

    def list_jobs(self, uid: str, limit: int) -> list[dict[str, Any]]:
        query = _jobs(uid).order_by("createdAt", direction=firestore.Query.DESCENDING).limit(limit)
        return [{"id": snap.id, **snap.to_dict()} for snap in query.stream()]

    def has_active_job(self, uid: str, stale_after: int) -> bool:
        query = _jobs(uid).where(
            filter=firestore.FieldFilter("status", "in", ["queued", "running"])
        )
        cutoff = now() - timedelta(seconds=stale_after)
        return any(snap.get("updatedAt") > cutoff for snap in query.stream())

    def get_index(self, video_id: str) -> dict[str, Any] | None:
        snap = _db().collection("library").document(video_id).get()
        return snap.to_dict() if snap.exists else None

    def save_index(self, video_id: str, data: dict[str, Any]) -> None:
        _db().collection("library").document(video_id).set({**data, "indexedAt": now()})


def get_store() -> Store:
    return Store()
