from datetime import UTC, datetime

from app.schemas import (
    CultureReport,
    Issue,
    Plan,
    Revision,
    Scene,
    SceneIndex,
    Selection,
    SubtitleLine,
    Subtitles,
)

RESPONSES = {
    Plan: Plan(
        scene_query="robot fight",
        market="Brazil",
        language="pt-BR",
        language_name="Portuguese",
        platform="TikTok",
        max_seconds=30,
        tone="hype",
    ),
    SceneIndex: SceneIndex(
        scenes=[
            Scene(
                start=60,
                end=80,
                description="Robots attack",
                dialogue="Run!",
                characters=[],
                mood="tense",
            )
        ]
    ),
    Selection: Selection(start=60, end=200, reason="Action"),
    Subtitles: Subtitles(
        lines=[SubtitleLine(start=0.5, end=2, original="Run!", translated="Corre!")]
    ),
    CultureReport: CultureReport(
        verdict="needs_changes",
        summary="Minor slang issue",
        issues=[
            Issue(
                time=1, category="language", severity="low", issue="Slang", suggestion="Use formal"
            )
        ],
        revisions=[Revision(index=0, translated="Revisado")],
        caption="Assista!",
        hashtags=["#anime"],
        thumbnail_title="Corre!",
        highlight_time=1.5,
    ),
}


class FakeGemini:
    def structured(self, model, contents, schema):
        return RESPONSES[schema]

    def image(self, model, prompt, reference_jpeg, aspect_ratio):
        return b"png"


class FakeMedia:
    def gcs_uri(self, path):
        return f"gs://bucket/{path}"

    def signed_url(self, path, minutes=60):
        return f"https://signed/{path}"

    def cut(self, src_path, start, end, name, vertical):
        return f"/tmp/{name}"

    def burn(self, clip, lines, name):
        return f"/tmp/{name}"

    def frame(self, src, at, name):
        return b"jpg"

    def upload_file(self, local_path, dest, content_type):
        return dest

    def upload_bytes(self, data, dest, content_type):
        return dest


class FakeStore:
    def __init__(self):
        self.docs: dict[str, list[dict]] = {}
        self.index: dict[str, dict] = {}

    def _find(self, uid, job_id):
        return next((d for d in self.docs.get(uid, []) if d["id"] == job_id), None)

    def create_job(self, uid, data):
        job_id = f"job{sum(len(v) for v in self.docs.values())}"
        now = datetime.now(UTC)
        self.docs.setdefault(uid, []).append(
            {"id": job_id, **data, "createdAt": now, "updatedAt": now}
        )
        return job_id

    def update_job(self, uid, job_id, data):
        doc = self._find(uid, job_id)
        for key, value in data.items():
            # Mimic Firestore dotted field paths.
            target = doc
            *parents, leaf = key.split(".")
            for p in parents:
                target = target.setdefault(p, {})
            target[leaf] = value

    def get_job(self, uid, job_id):
        return self._find(uid, job_id)

    def list_jobs(self, uid, limit):
        return list(reversed(self.docs.get(uid, [])))[:limit]

    def has_active_job(self, uid, stale_after):
        return any(d["status"] in ("queued", "running") for d in self.docs.get(uid, []))

    def get_index(self, video_id):
        return self.index.get(video_id)

    def save_index(self, video_id, data):
        self.index[video_id] = data
