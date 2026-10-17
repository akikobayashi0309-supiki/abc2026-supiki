import time
from functools import lru_cache
from typing import TypeVar

from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from app.config import get_settings

T = TypeVar("T", bound=BaseModel)

RETRYABLE = {429, 500, 503, 504}


@lru_cache
def _client() -> genai.Client:
    # Vertex AI mode with ADC: no API keys anywhere.
    settings = get_settings()
    return genai.Client(
        vertexai=True,
        project=settings.google_cloud_project or None,
        location=settings.google_cloud_location,
    )


def video_part(gcs_uri: str, low_res: bool = False) -> types.Part:
    return types.Part.from_uri(
        file_uri=gcs_uri,
        mime_type="video/mp4",
        media_resolution="MEDIA_RESOLUTION_LOW" if low_res else None,
    )


def _with_retry(call):
    for attempt in range(3):
        try:
            return call()
        except errors.APIError as exc:
            if exc.code not in RETRYABLE or attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


class Gemini:
    def structured(self, model: str, contents: list, schema: type[T]) -> T:
        """Generate JSON constrained to `schema` and parse it."""
        response = _with_retry(
            lambda: _client().models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                ),
            )
        )
        if isinstance(response.parsed, schema):
            return response.parsed
        return schema.model_validate_json(response.text or "{}")

    def image(self, model: str, prompt: str, reference_jpeg: bytes, aspect_ratio: str) -> bytes:
        """Generate an image from a reference frame and return PNG/JPEG bytes."""
        response = _with_retry(
            lambda: _client().models.generate_content(
                model=model,
                contents=[
                    types.Part.from_bytes(data=reference_jpeg, mime_type="image/jpeg"),
                    prompt,
                ],
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                    image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
                ),
            )
        )
        for candidate in response.candidates or []:
            for part in candidate.content.parts or []:
                if part.inline_data and part.inline_data.data:
                    return part.inline_data.data
        raise RuntimeError("Image model returned no image")


def get_gemini() -> Gemini:
    return Gemini()
