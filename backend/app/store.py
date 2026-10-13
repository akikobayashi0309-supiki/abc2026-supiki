from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from google.cloud import firestore

from app.config import get_settings


@lru_cache
def _db() -> firestore.Client:
    return firestore.Client(project=get_settings().google_cloud_project or None)


def _generations(uid: str) -> firestore.CollectionReference:
    # Per-user subcollection: ordering by createdAt needs no composite index.
    return _db().collection("users").document(uid).collection("generations")


class Store:
    def save_generation(self, uid: str, prompt: str, output: str, model: str) -> dict[str, Any]:
        doc = {
            "uid": uid,
            "prompt": prompt,
            "output": output,
            "model": model,
            "createdAt": datetime.now(UTC),
        }
        ref = _generations(uid).document()
        ref.set(doc)
        return {"id": ref.id, **doc}

    def list_generations(self, uid: str, limit: int) -> list[dict[str, Any]]:
        query = (
            _generations(uid)
            .order_by("createdAt", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        return [{"id": snap.id, **snap.to_dict()} for snap in query.stream()]


def get_store() -> Store:
    return Store()
