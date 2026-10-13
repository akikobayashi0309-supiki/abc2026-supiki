from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    google_cloud_project: str = ""
    # Gemini on Vertex AI is served from the global endpoint.
    google_cloud_location: str = "global"
    gemini_model: str = "gemini-2.5-flash"
    history_limit: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()
