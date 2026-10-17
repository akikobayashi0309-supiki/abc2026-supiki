"""The promo-clip agent: one request in, a localized, culture-checked short out."""

import json
import logging
from typing import Any

from app.config import Settings
from app.gemini import Gemini, video_part
from app.library import Video
from app.media import Media
from app.schemas import CultureReport, Plan, SceneIndex, Selection, SubtitleLine, Subtitles
from app.store import Store

log = logging.getLogger(__name__)

STEPS = ["plan", "search", "cut", "subtitles", "culture", "render", "assets"]
MIN_SECONDS = 5


class StepFailed(Exception):
    pass


def initial_steps() -> dict[str, dict[str, str]]:
    return {name: {"status": "pending"} for name in STEPS}


def clamp_selection(sel: Selection, duration: float, max_seconds: int) -> Selection:
    max_seconds = min(max(max_seconds, MIN_SECONDS), 60)
    start = min(max(sel.start, 0.0), max(duration - MIN_SECONDS, 0.0))
    end = min(max(sel.end, start + MIN_SECONDS), duration, start + max_seconds)
    return Selection(start=round(start, 2), end=round(end, 2), reason=sel.reason)


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


class Pipeline:
    def __init__(
        self,
        uid: str,
        job_id: str,
        video: Video,
        request: str,
        gemini: Gemini,
        media: Media,
        store: Store,
        settings: Settings,
    ) -> None:
        self.uid, self.job_id, self.video, self.request = uid, job_id, video, request
        self.gemini, self.media, self.store, self.settings = gemini, media, store, settings
        self.outputs: dict[str, str] = {}
        self.current = ""

    # -- bookkeeping -------------------------------------------------------

    def _update(self, data: dict[str, Any]) -> None:
        self.store.update_job(self.uid, self.job_id, data)

    def _step(self, name: str, status: str, detail: str = "", **data: Any) -> None:
        self.current = name
        self._update({f"steps.{name}": {"status": status, "detail": detail}, **data})

    def _out(self, path: str) -> str:
        return f"outputs/{self.uid}/{self.job_id}/{path}"

    # -- steps -------------------------------------------------------------

    def plan(self) -> Plan:
        prompt = (
            "You are a localization producer for game and anime marketing. Turn the request "
            "below into a production brief for a vertical short-form promo clip.\n"
            f"Source title: {self.video.title} — {self.video.synopsis}\n"
            f"Request: {self.request}\n"
            "If the market or platform is not stated, choose sensible defaults "
            "(platform TikTok, 30 seconds). maxSeconds must be between 10 and 60."
        )
        return self.gemini.structured(self.settings.reasoning_model, [prompt], Plan)

    def scene_index(self) -> SceneIndex:
        cached = self.store.get_index(self.video.id)
        if cached:
            return SceneIndex.model_validate(cached)
        prompt = (
            "Index this film for scene search. Split it into consecutive scenes of roughly "
            "5-40 seconds covering the whole film. For each scene give start and end in "
            "seconds from the beginning, a visual description, the spoken dialogue "
            "verbatim, the characters on screen and the mood."
        )
        index = self.gemini.structured(
            self.settings.video_model,
            [video_part(self.media.gcs_uri(self.video.path), low_res=True), prompt],
            SceneIndex,
        )
        self.store.save_index(self.video.id, _dump(index))
        return index

    def search(self, plan: Plan, index: SceneIndex) -> Selection:
        prompt = (
            "Pick the single best continuous moment for this promo brief from the scene "
            "index of the film. It may span adjacent scenes. Prefer moments that are "
            "striking without context and that include dialogue.\n"
            f"Brief: {plan.model_dump_json(by_alias=True)}\n"
            f"Film length: {self.video.duration} seconds. The clip must be at most "
            f"{plan.max_seconds} seconds.\n"
            f"Scene index: {index.model_dump_json(by_alias=True)}"
        )
        sel = self.gemini.structured(self.settings.reasoning_model, [prompt], Selection)
        return clamp_selection(sel, self.video.duration, plan.max_seconds)

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
            "text. Only report real risks; an empty issue list is fine.\n"
            f"Then write a post caption and 3-8 hashtags in {plan.language_name} in a "
            f"{plan.tone} tone, a short thumbnail title in {plan.language_name}, and the "
            "best thumbnail moment (seconds into the clip).\n"
            f"Subtitles: {json.dumps(numbered, ensure_ascii=False)}"
        )
        return self.gemini.structured(
            self.settings.reasoning_model, [video_part(clip_uri), prompt], CultureReport
        )

    def thumbnail(self, plan: Plan, report: CultureReport, frame: bytes) -> bytes:
        prompt = (
            f"Design a vertical 9:16 {plan.platform} cover image for viewers in {plan.market}, "
            f"using this frame from the film '{self.video.title}' as the key visual. Keep the "
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

    def _run(self) -> None:
        self._step("plan", "running")
        plan = self.plan()
        self._step(
            "plan", "done", f"{plan.platform} · {plan.market} · {plan.language}", plan=_dump(plan)
        )

        self._step("search", "running", "Reading the scene index")
        index = self.scene_index()
        selection = self.search(plan, index)
        self._step(
            "search",
            "done",
            f"{selection.start:.1f}s – {selection.end:.1f}s of {len(index.scenes)} scenes",
            selection=_dump(selection),
        )

        self._step("cut", "running")
        raw = self.media.cut(self.video.path, selection.start, selection.end, "raw.mp4", False)
        vertical = self.media.cut(
            self.video.path, selection.start, selection.end, "vertical.mp4", True
        )
        raw_path = self.media.upload_file(raw, self._out("raw.mp4"), "video/mp4")
        self.outputs["clip"] = self.media.upload_file(vertical, self._out("clip.mp4"), "video/mp4")
        self._step("cut", "done", "9:16 with blurred background", outputs=self.outputs)
        clip_uri = self.media.gcs_uri(raw_path)

        lines: list[SubtitleLine] = []
        self._step("subtitles", "running")
        try:
            lines = self.subtitles(plan, clip_uri)
            self._step(
                "subtitles", "done", f"{len(lines)} lines", subtitles=[_dump(x) for x in lines]
            )
        except Exception as exc:
            log.exception("subtitles failed")
            self._step("subtitles", "failed", str(exc)[:200])

        report: CultureReport | None = None
        self._step("culture", "running")
        try:
            report = self.culture(plan, clip_uri, lines)
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
                final = self.media.burn(vertical, final_lines, "final.mp4")
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
