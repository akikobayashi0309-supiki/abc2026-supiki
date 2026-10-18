"""Structured-output schemas returned by Gemini."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class Schema(BaseModel):
    # camelCase on the wire (Gemini JSON, Firestore, API) to match the frontend.
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Plan(Schema):
    scene_query: str = Field(description="What scene to look for, in English")
    market: str = Field(description="Target country or region, e.g. 'Brazil'")
    language: str = Field(description="BCP-47 subtitle language, e.g. 'pt-BR'")
    language_name: str = Field(description="Subtitle language name in English")
    platform: str = Field(description="Target platform, e.g. 'TikTok'")
    max_seconds: int = Field(description="Maximum clip length in seconds (10-60)")
    tone: str = Field(description="Desired tone of the post")
    requested_title: str = Field(
        default="",
        description="Specific anime, game or film title the request names, as written; "
        "empty if the request only describes a topic or mood",
    )


class Scene(Schema):
    start: float = Field(description="Scene start in seconds from the beginning")
    end: float = Field(description="Scene end in seconds from the beginning")
    description: str
    dialogue: str = Field(description="Spoken lines in the scene, verbatim if possible")
    characters: list[str]
    mood: str


class SceneIndex(Schema):
    summary: str = Field(default="", description="One-paragraph synopsis of the whole video")
    scenes: list[Scene]


class Selection(Schema):
    start: float = Field(description="Clip start in seconds")
    end: float = Field(description="Clip end in seconds")
    reason: str = Field(description="Why this moment works for the request")


class LibrarySelection(Schema):
    title_found: bool = Field(
        default=True,
        description="False if the brief names a specific title and no video in the "
        "library is footage of that title",
    )
    video_id: str = Field(description="ID of the chosen video")
    start: float = Field(description="Clip start in seconds")
    end: float = Field(description="Clip end in seconds")
    reason: str = Field(description="Why this moment works for the request")


class SubtitleLine(Schema):
    start: float = Field(description="Seconds from the start of the clip")
    end: float = Field(description="Seconds from the start of the clip")
    original: str
    translated: str


class Subtitles(Schema):
    lines: list[SubtitleLine]


class Issue(Schema):
    time: float = Field(description="Seconds from the start of the clip")
    category: Literal[
        "gesture", "religion", "violence", "symbol", "color_number", "language", "legal", "other"
    ]
    severity: Literal["low", "medium", "high"]
    issue: str
    suggestion: str


class Revision(Schema):
    index: int = Field(description="Index of the subtitle line to replace")
    translated: str = Field(description="Culturally adjusted subtitle text")


class CultureReport(Schema):
    verdict: Literal["ready", "needs_changes", "not_recommended"]
    summary: str
    issues: list[Issue]
    revisions: list[Revision]
    caption: str = Field(description="Post caption in the target language")
    hashtags: list[str]
    thumbnail_title: str = Field(description="Short catchy title in the target language")
    highlight_time: float = Field(description="Best frame for a thumbnail, seconds into the clip")
