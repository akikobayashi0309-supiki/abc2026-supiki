from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    google_cloud_project: str = ""
    # Gemini on Vertex AI is served from the global endpoint.
    google_cloud_location: str = "global"
    # Latest models for every step, each with a stable fallback used on
    # quota or availability errors so the demo keeps running.
    reasoning_model: str = "gemini-4-argon"
    video_model: str = "gemini-4-argon"
    fallback_model: str = "gemini-3.8-flash"
    image_model: str = "gemini-nano-banana-2.1"
    image_fallback_model: str = "gemini-3.1-flash-image"
    media_bucket: str = ""
    history_limit: int = 20
    # A running job older than this is treated as dead (e.g. instance recycled).
    stale_job_seconds: int = 900


@lru_cache
def get_settings() -> Settings:
    return Settings()
