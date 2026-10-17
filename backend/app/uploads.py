"""Turn an uploaded file into a library video: validate, normalize, index."""

import logging

from app.config import Settings
from app.gemini import Gemini
from app.library import uploaded_video
from app.media import Media
from app.pipeline import build_index
from app.store import Store

log = logging.getLogger(__name__)

CONTENT_TYPES = {"video/mp4", "video/quicktime", "video/webm"}


def process_upload(
    uid: str, video_id: str, gemini: Gemini, media: Media, store: Store, settings: Settings
) -> None:
    doc = store.get_video(uid, video_id)
    if not doc:
        return
    try:
        store.update_video(uid, video_id, {"status": "processing"})
        duration = media.duration(doc["sourcePath"])
        if duration > settings.max_upload_seconds:
            raise ValueError(
                f"Video is {duration / 60:.0f} min; the limit is "
                f"{settings.max_upload_seconds // 60} min."
            )
        normalized = media.normalize(doc["sourcePath"], "video.mp4")
        media.upload_file(normalized, doc["path"], "video/mp4")
        poster = media.frame(normalized, min(duration / 3, 30), "poster.jpg")
        media.upload_bytes(poster, doc["posterPath"], "image/jpeg")
        store.update_video(uid, video_id, {"status": "indexing", "duration": int(duration)})

        video = uploaded_video({**doc, "duration": int(duration)})
        index = build_index(gemini, media, store, settings, video)
        store.update_video(uid, video_id, {"status": "ready", "synopsis": index.summary})
    except Exception as exc:
        log.exception("upload %s failed", video_id)
        store.update_video(uid, video_id, {"status": "failed", "error": str(exc)[:300]})
