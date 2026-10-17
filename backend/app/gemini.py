import logging
import time
from typing import TypeVar

from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from app.config import get_settings

T = TypeVar("T", bound=BaseModel)

log = logging.getLogger(__name__)

RETRYABLE = {429, 500, 503, 504}
# Fall back to the stable model on these (quota, missing or retired model, outages).
FALLBACK_ON = RETRYABLE | {404}
BACKOFF = [2, 5, 10, 20]


def _new_client() -> genai.Client:
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
    for delay in [*BACKOFF, None]:
        try:
            return call()
        except errors.APIError as exc:
            if exc.code not in RETRYABLE or delay is None:
                raise
            time.sleep(delay)


class Gemini:
    def __init__(self) -> None:
        # One client per job: a shared client was closed under concurrent jobs.
        self.client = _new_client()
        # Model that served the most recent call (shown in the UI).
        self.last_model = ""

    def _generate(self, models: list[str], contents: list, config: types.GenerateContentConfig):
        for i, model in enumerate(models):
            try:
                response = _with_retry(
                    lambda m=model: self.client.models.generate_content(
                        model=m, contents=contents, config=config
                    )
                )
                self.last_model = model
                return response
            except errors.APIError as exc:
                if exc.code not in FALLBACK_ON or i == len(models) - 1:
                    raise
                log.warning("%s failed with %s; falling back to %s", model, exc.code, models[i + 1])

    def _chain(self, model: str, fallback: str) -> list[str]:
        return [model] if model == fallback else [model, fallback]

    def structured(self, model: str, contents: list, schema: type[T]) -> T:
        """Generate JSON constrained to `schema` and parse it."""
        response = self._generate(
            self._chain(model, get_settings().fallback_model),
            contents,
            types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )
        if isinstance(response.parsed, schema):
            return response.parsed
        return schema.model_validate_json(response.text or "{}")

    def image(self, model: str, prompt: str, reference_jpeg: bytes, aspect_ratio: str) -> bytes:
        """Generate an image from a reference frame and return PNG/JPEG bytes."""
        response = self._generate(
            self._chain(model, get_settings().image_fallback_model),
            [types.Part.from_bytes(data=reference_jpeg, mime_type="image/jpeg"), prompt],
            types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
            ),
        )
        for candidate in response.candidates or []:
            for part in candidate.content.parts or []:
                if part.inline_data and part.inline_data.data:
                    return part.inline_data.data
        raise RuntimeError("Image model returned no image")


def get_gemini() -> Gemini:
    return Gemini()
