"""The promo-clip agent: one request in, a localized, culture-checked short out."""

import json
import logging
import time
from datetime import date
from typing import Any

from app.config import Settings
from app.gemini import Gemini, video_part
from app.library import Video
from app.media import Media
from app.schemas import (
    CultureReport,
    LibrarySelection,
    Plan,
    SceneIndex,
    Selection,
    SubtitleLine,
    Subtitles,
)
from app.store import Store

log = logging.getLogger(__name__)

STEPS = ["plan", "trends", "search", "subtitles", "cut", "culture", "render", "assets"]
MIN_SECONDS = 5
GEMINI_STEPS = {"plan", "trends", "search", "subtitles", "culture", "assets"}
# Transcribe this much extra footage around the selection to snap to real dialogue.
WINDOW_PAD = 20.0


class StepFailed(Exception):
    pass


class MissingFootage(Exception):
    """The request names a title the library has no footage of."""


def initial_steps() -> dict[str, dict[str, str]]:
    return {name: {"status": "pending"} for name in STEPS}


def clamp_selection(sel: Selection, duration: float, max_seconds: int) -> Selection:
    max_seconds = min(max(max_seconds, MIN_SECONDS), 60)
    start = min(max(sel.start, 0.0), max(duration - MIN_SECONDS, 0.0))
    end = min(max(sel.end, start + MIN_SECONDS), duration, start + max_seconds)
    return Selection(start=round(start, 2), end=round(end, 2), reason=sel.reason)


def normalize_index(index: SceneIndex, duration: float) -> SceneIndex:
    """Rescale timestamps if the model's timeline overshoots the real film length."""
    last = max((scene.end for scene in index.scenes), default=0.0)
    ratio = duration / last if last > duration * 1.02 else 1.0
    scenes = []
    for scene in index.scenes:
        start = min(round(scene.start * ratio, 2), duration)
        end = min(max(round(scene.end * ratio, 2), start), duration)
        scenes.append(scene.model_copy(update={"start": start, "end": end}))
    return SceneIndex(scenes=scenes)


def shift(lines: list[SubtitleLine], offset: float) -> list[SubtitleLine]:
    return [
        line.model_copy(update={"start": line.start + offset, "end": line.end + offset})
        for line in lines
    ]


def align_selection(sel: Selection, lines: list[SubtitleLine], duration: float) -> Selection:
    """Move the clip onto real dialogue when the scene index timing missed it.

    `lines` use absolute film time.
    """
    if not lines or any(line.end > sel.start and line.start < sel.end for line in lines):
        return sel
    nearest = min(lines, key=lambda line: abs(line.start - sel.start))
    length = sel.end - sel.start
    start = max(0.0, min(nearest.start - 0.5, duration - length))
    return Selection(start=round(start, 2), end=round(start + length, 2), reason=sel.reason)


def lines_in(lines: list[SubtitleLine], sel: Selection) -> list[SubtitleLine]:
    """Lines overlapping the selection, relative to the clip start."""
    length = sel.end - sel.start
    return [
        line.model_copy(
            update={
                "start": round(max(line.start - sel.start, 0.0), 2),
                "end": round(min(line.end - sel.start, length), 2),
            }
        )
        for line in lines
        if line.end > sel.start and line.start < sel.end
    ]


def hashtags(tags: list[str]) -> list[str]:
    return ["#" + tag.lstrip("#").replace(" ", "") for tag in tags if tag.strip("# ")]


def apply_revisions(lines: list[SubtitleLine], report: CultureReport | None) -> list[SubtitleLine]:
    if not report:
        return lines
    revised = [line.model_copy() for line in lines]
    for rev in report.revisions:
        if 0 <= rev.index < len(revised):
            revised[rev.index].translated = rev.translated
    return revised


def _dump(model: Any) -> Any:
    return model.model_dump(by_alias=True)


def build_index(
    gemini: Gemini, media: Media, store: Store, settings: Settings, video: Video
) -> SceneIndex:
    """Scene index for a video, built once with Gemini video understanding and cached."""
    cached = store.get_index(video.id)
    if cached:
        return normalize_index(SceneIndex.model_validate(cached), video.duration)
    minutes, seconds = divmod(video.duration, 60)
    prompt = (
        "Index this video for scene search. It is exactly "
        f"{minutes}:{seconds:02d} (MM:SS) long, i.e. {video.duration} seconds. Split it "
        "into consecutive scenes of roughly 5-40 seconds covering the whole video. Read "
        "each timestamp as MM:SS from the video timeline and convert it to seconds; no "
        f"value may exceed {video.duration}. For each scene give start and end, a "
        "visual description, the spoken dialogue verbatim, the characters on screen and "
        "the mood. Also write a one-paragraph summary of the whole video."
    )
    index = gemini.structured(
        settings.video_model, [video_part(media.gcs_uri(video.path)), prompt], SceneIndex
    )
    index = normalize_index(index, video.duration)
    store.save_index(video.id, _dump(index))
    return index


class Pipeline:
    def __init__(
        self,
        uid: str,
        job_id: str,
        candidates: list[Video],
        request: str,
        gemini: Gemini,
        media: Media,
        store: Store,
        settings: Settings,
        leader_id: str | None = None,
    ) -> None:
        """`candidates` holds one video, or several when the agent should pick the film.

        `leader_id` makes this job reuse the clip chosen by another job in the same
        market-comparison batch, so every market reviews the same footage.
        """
        self.uid, self.job_id, self.request = uid, job_id, request
        self.candidates = candidates
        self.video = candidates[0]
        self.gemini, self.media, self.store, self.settings = gemini, media, store, settings
        self.leader_id = leader_id
        self.outputs: dict[str, str] = {}
        self.current = ""
        self.trends = ""

    # -- bookkeeping -------------------------------------------------------

    def _update(self, data: dict[str, Any]) -> None:
        self.store.update_job(self.uid, self.job_id, data)

    def _step(self, name: str, status: str, detail: str = "", **data: Any) -> None:
        self.current = name
        step = {"status": status, "detail": detail}
        if status == "done" and name in GEMINI_STEPS:
            step["model"] = getattr(self.gemini, "last_model", "")
        self._update({f"steps.{name}": step, **data})

    def _out(self, path: str) -> str:
        return f"outputs/{self.uid}/{self.job_id}/{path}"

    def _source(self) -> str:
        if len(self.candidates) > 1:
            return "a library of videos: " + "; ".join(
                f"{v.title} — {v.synopsis}" for v in self.candidates
            )
        return f"{self.video.title} — {self.video.synopsis}"

    # -- steps -------------------------------------------------------------

    def plan(self) -> Plan:
        prompt = (
            "You are a localization producer for game and anime marketing. Turn the request "
            "below into a production brief for a vertical short-form promo clip.\n"
            f"Source: {self._source()}\n"
            f"Request: {self.request}\n"
            "If the market or platform is not stated, choose sensible defaults "
            "(platform TikTok, 30 seconds). maxSeconds must be between 10 and 60."
        )
        return self.gemini.structured(self.settings.reasoning_model, [prompt], Plan)

    def research_trends(self, plan: Plan) -> tuple[str, list[dict]]:
        prompt = (
            f"Today is {date.today().isoformat()}. You are a social media trend researcher. "
            f"Using Google Search, find what is trending right now on {plan.platform} in "
            f"{plan.market} for content like this: {plan.scene_query} (tone: {plan.tone}). "
            "Cover popular anime, game and pop-culture topics this season, viral formats, "
            "hooks or memes, and hashtags people actually use. Answer in English with at most "
            "8 short bullet points; no preamble."
        )
        return self.gemini.grounded(self.settings.reasoning_model, prompt)

    def search(self, plan: Plan, index: SceneIndex) -> Selection:
        prompt = (
            "Pick the single best continuous moment for this promo brief from the scene "
            "index of the video. It may span adjacent scenes. The clip will be subtitled in "
            "the target language, so it must include at least one scene whose dialogue is "
            "not empty, and the spoken lines should land early in the clip. Start the clip "
            "at the start time of a scene in the index. Prefer moments that are striking "
            "without context and that fit current trends.\n"
            f"Brief: {plan.model_dump_json(by_alias=True)}\n"
            f"Current trends in the market: {self.trends or 'unknown'}\n"
            f"Video length: {self.video.duration} seconds. The clip must be at most "
            f"{plan.max_seconds} seconds.\n"
            f"Scene index: {index.model_dump_json(by_alias=True)}"
        )
        sel = self.gemini.structured(self.settings.reasoning_model, [prompt], Selection)
        return clamp_selection(sel, self.video.duration, plan.max_seconds)

    def search_library(self, plan: Plan, indexes: dict[str, SceneIndex]) -> Selection:
        catalog = [
            {
                "videoId": v.id,
                "title": v.title,
                "duration": v.duration,
                "index": _dump(indexes[v.id]),
            }
            for v in self.candidates
        ]
        prompt = (
            "Pick the single best video and continuous moment for this promo brief from the "
            "scene indexes below. If the brief names a specific title (requestedTitle), only "
            "footage of that exact title counts: set titleFound to false when no video is "
            "that title, even if another video has a similar theme. The clip will be "
            "subtitled, so it must include spoken "
            "dialogue early on. Start at the start time of a scene. Prefer moments that are "
            "striking without context and that fit current trends.\n"
            f"Brief: {plan.model_dump_json(by_alias=True)}\n"
            f"Current trends in the market: {self.trends or 'unknown'}\n"
            f"The clip must be at most {plan.max_seconds} seconds.\n"
            f"Library: {json.dumps(catalog, ensure_ascii=False)}"
        )
        sel = self.gemini.structured(self.settings.reasoning_model, [prompt], LibrarySelection)
        if plan.requested_title and not sel.title_found:
            # Never pass off a different work as the requested one.
            raise MissingFootage(
                f'No footage of "{plan.requested_title}" in the library. Upload official '
                "footage you have the rights to (e.g. a trailer or gameplay capture), then "
                "pick it as the source or run Agent picks again."
            )
        self.video = next((v for v in self.candidates if v.id == sel.video_id), self.video)
        plain = Selection(start=sel.start, end=sel.end, reason=sel.reason)
        return clamp_selection(plain, self.video.duration, plan.max_seconds)

    def follow_leader(self, timeout_s: int = 900) -> Selection | None:
        """Wait for the batch leader to cut its clip, then reuse the same range."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            leader = self.store.get_job(self.uid, self.leader_id) or {}
            clip = leader.get("clipRange")
            if clip:
                self.video = next(
                    (v for v in self.candidates if v.id == clip["videoId"]), self.video
                )
                return Selection(
                    start=clip["start"], end=clip["end"], reason=clip.get("reason", "")
                )
            if leader.get("status") == "failed":
                return None
            time.sleep(3)
        return None

    def subtitles(self, plan: Plan, clip_uri: str) -> list[SubtitleLine]:
        prompt = (
            "Transcribe every spoken line in this clip with start and end times in seconds "
            "from the start of the clip, then translate each line into "
            f"{plan.language_name} ({plan.language}) for {plan.market} viewers. Keep "
            "translations natural and short enough for vertical video (max ~40 characters "
            "per line). Return an empty list if nobody speaks."
        )
        result = self.gemini.structured(
            self.settings.video_model, [video_part(clip_uri), prompt], Subtitles
        )
        return result.lines

    def culture(self, plan: Plan, clip_uri: str, lines: list[SubtitleLine]) -> CultureReport:
        numbered = [{"index": i, **_dump(line)} for i, line in enumerate(lines)]
        prompt = (
            f"You are a cultural compliance reviewer for {plan.market}. Review this clip and "
            f"its {plan.language_name} subtitles before it is posted on {plan.platform}.\n"
            "Check gestures, religious references, violence and weapons (including local "
            "platform and age-rating rules), symbols, colors and numbers, and translation "
            "nuance or slang. Report concrete issues with the time in the clip, severity and "
            "a fix. For subtitle problems, add a revision with the line index and corrected "
            "text. Only report real, specific risks; an empty issue list is fine. The output "
            "is a draft for a human reviewer.\n"
            f"Then write a post caption and 3-8 hashtags in {plan.language_name} in a "
            f"{plan.tone} tone that ride the current trends below where they genuinely fit "
            "(formats, hooks, seasonal topics and generic hashtags only: never name or tag "
            "other franchises, titles or brands, which is misleading and risks takedowns), a "
            f"short thumbnail title in {plan.language_name}, and the best thumbnail moment "
            "(seconds into the clip).\n"
            f"Current trends: {self.trends or 'unknown'}\n"
            f"Subtitles: {json.dumps(numbered, ensure_ascii=False)}"
        )
        return self.gemini.structured(
            self.settings.reasoning_model, [video_part(clip_uri), prompt], CultureReport
        )

    def thumbnail(self, plan: Plan, report: CultureReport, frame: bytes) -> bytes:
        prompt = (
            f"Design a vertical 9:16 {plan.platform} cover image for viewers in {plan.market}, "
            f"using this frame from '{self.video.title}' as the key visual. Keep the "
            "characters and scene recognizable. Add the headline "
            f'"{report.thumbnail_title}" in {plan.language_name}, large, bold and legible, '
            "spelled exactly as given. No logos, watermarks or extra text."
        )
        return self.gemini.image(self.settings.image_model, prompt, frame, "9:16")

    # -- orchestration -----------------------------------------------------

    def run(self) -> None:
        self._update({"status": "running"})
        try:
            self._run()
            self._update({"status": "done", "outputs": self.outputs})
        except MissingFootage as exc:
            self._update(
                {
                    "status": "failed",
                    "error": str(exc),
                    "missingFootage": True,
                    f"steps.{self.current}": {"status": "failed", "detail": "No matching footage"},
                }
            )
        except Exception as exc:
            log.exception("job %s failed", self.job_id)
            self._update(
                {
                    "status": "failed",
                    "error": str(exc)[:500],
                    "outputs": self.outputs,
                    f"steps.{self.current}": {"status": "failed", "detail": "Stopped here"},
                }
            )

    def _video_fields(self) -> dict[str, str]:
        return {"videoId": self.video.id, "videoTitle": self.video.title}

    def _run(self) -> None:
        self._step("plan", "running")
        plan = self.plan()
        self._step(
            "plan", "done", f"{plan.platform} · {plan.market} · {plan.language}", plan=_dump(plan)
        )

        self._step("trends", "running", f"Searching what is trending in {plan.market}")
        try:
            self.trends, sources = self.research_trends(plan)
            self._step(
                "trends",
                "done",
                f"{len(sources)} sources",
                trends={"summary": self.trends, "sources": sources},
            )
        except Exception as exc:
            log.exception("trend research failed")
            self._step("trends", "skipped", f"Unavailable: {str(exc)[:120]}")

        fixed = False
        selection: Selection | None = None
        if self.leader_id:
            self._step("search", "running", "Using the same scene as the other markets")
            selection = self.follow_leader()
            fixed = selection is not None
        if selection is None:
            self._step("search", "running", "Reading the scene index")
            if len(self.candidates) > 1:
                indexes = {
                    v.id: build_index(self.gemini, self.media, self.store, self.settings, v)
                    for v in self.candidates
                }
                selection = self.search_library(plan, indexes)
                scenes = sum(len(i.scenes) for i in indexes.values())
                detail = (
                    f"{self.video.title}: {selection.start:.1f}s – {selection.end:.1f}s "
                    f"of {scenes} scenes"
                )
            else:
                index = build_index(self.gemini, self.media, self.store, self.settings, self.video)
                selection = self.search(plan, index)
                detail = (
                    f"{selection.start:.1f}s – {selection.end:.1f}s of {len(index.scenes)} scenes"
                )
        else:
            detail = f"Shared scene {selection.start:.1f}s – {selection.end:.1f}s"
        self._step("search", "done", detail, selection=_dump(selection), **self._video_fields())

        self._step("subtitles", "running", "Listening around the scene")
        duration = float(self.video.duration)
        pad = 0.0 if fixed else WINDOW_PAD
        w_start = max(0.0, selection.start - pad)
        w_end = min(duration, selection.end + pad)
        window = self.media.cut(self.video.path, w_start, w_end, "window.mp4", False)
        window_uri = self.media.gcs_uri(
            self.media.upload_file(window, self._out("window.mp4"), "video/mp4")
        )
        lines: list[SubtitleLine] = []
        try:
            heard = shift(self.subtitles(plan, window_uri), w_start)
            if not fixed:
                selection = align_selection(selection, heard, duration)
            lines = lines_in(heard, selection)
            self._step(
                "subtitles",
                "done",
                f"{len(lines)} lines",
                subtitles=[_dump(x) for x in lines],
                selection=_dump(selection),
            )
        except Exception as exc:
            log.exception("subtitles failed")
            self._step("subtitles", "failed", str(exc)[:200])

        self._step("cut", "running")
        raw = self.media.cut(self.video.path, selection.start, selection.end, "raw.mp4", False)
        vertical = self.media.cut(
            self.video.path, selection.start, selection.end, "vertical.mp4", True
        )
        raw_path = self.media.upload_file(raw, self._out("raw.mp4"), "video/mp4")
        self.outputs["clip"] = self.media.upload_file(vertical, self._out("clip.mp4"), "video/mp4")
        self._step(
            "cut",
            "done",
            f"{selection.start:.1f}s – {selection.end:.1f}s, 9:16",
            outputs=self.outputs,
            clipRange={
                "videoId": self.video.id,
                "start": selection.start,
                "end": selection.end,
                "reason": selection.reason,
            },
        )
        clip_uri = self.media.gcs_uri(raw_path)

        report: CultureReport | None = None
        self._step("culture", "running")
        try:
            report = self.culture(plan, clip_uri, lines)
            report.hashtags = hashtags(report.hashtags)
            self._step(
                "culture",
                "done",
                f"{report.verdict} · {len(report.issues)} issues",
                culture=_dump(report),
            )
        except Exception as exc:
            log.exception("culture check failed")
            self._step("culture", "failed", str(exc)[:200])

        self._step("render", "running")
        final_lines = apply_revisions(lines, report)
        if final_lines:
            try:
                final = self.media.burn(vertical, final_lines, "final.mp4", plan.language)
                self.outputs["final"] = self.media.upload_file(
                    final, self._out("final.mp4"), "video/mp4"
                )
                self._step(
                    "render",
                    "done",
                    f"Burned {len(final_lines)} subtitles",
                    finalSubtitles=[_dump(x) for x in final_lines],
                    outputs=self.outputs,
                )
            except Exception as exc:
                log.exception("render failed")
                self.outputs["final"] = self.outputs["clip"]
                self._step("render", "failed", str(exc)[:200], outputs=self.outputs)
        else:
            self.outputs["final"] = self.outputs["clip"]
            self._step("render", "skipped", "No dialogue to subtitle", outputs=self.outputs)

        self._step("assets", "running")
        try:
            at = report.highlight_time if report else (selection.end - selection.start) / 2
            frame = self.media.frame(raw, at, "keyframe.jpg")
            self.outputs["keyframe"] = self.media.upload_bytes(
                frame, self._out("keyframe.jpg"), "image/jpeg"
            )
            self._update({"outputs": self.outputs})
            if report:
                image = self.thumbnail(plan, report, frame)
                self.outputs["thumbnail"] = self.media.upload_bytes(
                    image, self._out("thumbnail.png"), "image/png"
                )
            self._step("assets", "done", "Keyframe and thumbnail", outputs=self.outputs)
        except Exception as exc:
            log.exception("assets failed")
            self._step("assets", "failed", str(exc)[:200], outputs=self.outputs)
