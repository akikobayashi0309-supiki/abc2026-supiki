from functools import lru_cache

from google import genai

from app.config import get_settings


@lru_cache
def _client() -> genai.Client:
    # Vertex AI mode with ADC: no API keys anywhere.
    settings = get_settings()
    return genai.Client(
        vertexai=True,
        project=settings.google_cloud_project or None,
        location=settings.google_cloud_location,
    )


class Gemini:
    def generate(self, prompt: str) -> str:
        response = _client().models.generate_content(
            model=get_settings().gemini_model,
            contents=prompt,
        )
        return response.text or ""


def get_gemini() -> Gemini:
    return Gemini()
