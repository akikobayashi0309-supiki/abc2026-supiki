import datetime as dt
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

import google.auth
from google.auth.transport.requests import Request
from google.cloud import storage

from app.config import get_settings
from app.schemas import SubtitleLine

WIDTH, HEIGHT = 720, 1280  # 9:16 vertical output
# Library films are ~2.4:1; zoom in so the subject fills more of the frame.
FG_HEIGHT = 460

# Blurred, zoomed copy of the frame as background with the original frame centered on top.
VERTICAL_FILTER = (
    f"[0:v]split[a][b];"
    f"[a]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
    f"crop={WIDTH}:{HEIGHT},boxblur=20:2[bg];"
    f"[b]scale=-2:{FG_HEIGHT},crop={WIDTH}:{FG_HEIGHT}[fg];"
    f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[v]"
)

# libass styles use a 288px-high reference canvas; this lands in the lower blurred band.
SUBTITLE_STYLE = (
    "FontName={font},FontSize=15,Bold=1,PrimaryColour=&H00FFFFFF,"
    "OutlineColour=&H00000000,BorderStyle=1,Outline=1.5,Shadow=0,Alignment=2,MarginV=60"
)

# libass does not reliably fall back across scripts, so pick a Noto family per language.
FONTS = {
    "ar": "Noto Sans Arabic",
    "fa": "Noto Sans Arabic",
    "ur": "Noto Sans Arabic",
    "he": "Noto Sans Hebrew",
    "th": "Noto Sans Thai",
    "hi": "Noto Sans Devanagari",
    "mr": "Noto Sans Devanagari",
    "bn": "Noto Sans Bengali",
    "ta": "Noto Sans Tamil",
    "ja": "Noto Sans CJK JP",
    "ko": "Noto Sans CJK KR",
    "zh": "Noto Sans CJK SC",
    "zh-tw": "Noto Sans CJK TC",
    "zh-hk": "Noto Sans CJK TC",
}


def font_for(language: str) -> str:
    tag = language.lower().replace("_", "-")
    return FONTS.get(tag) or FONTS.get(tag.split("-")[0]) or "Noto Sans"


ENCODE = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-movflags", "+faststart"]


def cut_args(src: str, start: float, end: float, out: str, vertical: bool) -> list[str]:
    args = ["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.2f}", "-i", src]
    args += ["-t", f"{max(end - start, 1):.2f}"]
    if vertical:
        args += ["-filter_complex", VERTICAL_FILTER, "-map", "[v]", "-map", "0:a?"]
    args += [*ENCODE, "-c:a", "aac", "-b:a", "128k", out]
    return args


def burn_args(src: str, srt: str, out: str, font: str = "Noto Sans") -> list[str]:
    vf = f"subtitles={srt}:force_style='{SUBTITLE_STYLE.format(font=font)}'"
    return ["ffmpeg", "-v", "error", "-y", "-i", src, "-vf", vf, *ENCODE, "-c:a", "copy", out]


def frame_args(src: str, at: float, out: str) -> list[str]:
    return ["ffmpeg", "-v", "error", "-y", "-ss", f"{at:.2f}", "-i", src, "-frames:v", "1", out]


def normalize_args(src: str, out: str) -> list[str]:
    # 720p H.264/AAC with faststart so ffmpeg can seek over HTTP and Gemini reads it as MP4.
    return [
        "ffmpeg", "-v", "error", "-y", "-i", src, "-map", "0:v:0", "-map", "0:a:0?",
        "-vf", "scale=-2:'min(720,ih)'", *ENCODE, "-c:a", "aac", "-b:a", "128k", "-ac", "2", out,
    ]  # fmt: skip


def probe_duration(src: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("Could not read the video. Is it a valid MP4, MOV or WebM file?")
    return float(result.stdout.strip())


def _timestamp(seconds: float) -> str:
    ms = max(int(round(seconds * 1000)), 0)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(lines: list[SubtitleLine]) -> str:
    blocks = []
    for i, line in enumerate(lines, start=1):
        blocks.append(
            f"{i}\n{_timestamp(line.start)} --> {_timestamp(line.end)}\n{line.translated}\n"
        )
    return "\n".join(blocks)


def _run(args: list[str]) -> None:
    result = subprocess.run(args, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr[-500:]}")


@lru_cache
def _storage() -> storage.Client:
    return storage.Client(project=get_settings().google_cloud_project or None)


class Media:
    """ffmpeg processing plus Cloud Storage I/O for one job."""

    def __init__(self) -> None:
        self.bucket = _storage().bucket(get_settings().media_bucket)
        self.workdir = Path(tempfile.mkdtemp(prefix="job-"))

    def gcs_uri(self, path: str) -> str:
        return f"gs://{self.bucket.name}/{path}"

    def signed_url(self, path: str, minutes: int = 60) -> str:
        # On Cloud Run the runtime SA signs through the IAM API (needs Token Creator on itself).
        credentials, _ = google.auth.default()
        if not credentials.valid:
            credentials.refresh(Request())
        return self.bucket.blob(path).generate_signed_url(
            version="v4",
            expiration=dt.timedelta(minutes=minutes),
            service_account_email=getattr(credentials, "service_account_email", None),
            access_token=credentials.token,
        )

    def signed_upload_url(self, path: str, content_type: str, minutes: int = 30) -> str:
        credentials, _ = google.auth.default()
        if not credentials.valid:
            credentials.refresh(Request())
        return self.bucket.blob(path).generate_signed_url(
            version="v4",
            method="PUT",
            content_type=content_type,
            expiration=dt.timedelta(minutes=minutes),
            service_account_email=getattr(credentials, "service_account_email", None),
            access_token=credentials.token,
        )

    def size(self, path: str) -> int | None:
        blob = self.bucket.get_blob(path)
        return blob.size if blob else None

    def duration(self, path: str) -> float:
        return probe_duration(self.signed_url(path))

    def normalize(self, src_path: str, name: str) -> str:
        out = self.local(name)
        _run(normalize_args(self.signed_url(src_path), out))
        return out

    def local(self, name: str) -> str:
        return str(self.workdir / name)

    def cut(self, src_path: str, start: float, end: float, name: str, vertical: bool) -> str:
        out = self.local(name)
        _run(cut_args(self.signed_url(src_path), start, end, out, vertical))
        return out

    def burn(self, clip: str, lines: list[SubtitleLine], name: str, language: str) -> str:
        srt = self.local("subs.srt")
        Path(srt).write_text(to_srt(lines), encoding="utf-8")
        out = self.local(name)
        _run(burn_args(clip, srt, out, font_for(language)))
        return out

    def frame(self, src: str, at: float, name: str) -> bytes:
        out = self.local(name)
        _run(frame_args(src, at, out))
        return Path(out).read_bytes()

    def upload_file(self, local_path: str, dest: str, content_type: str) -> str:
        self.bucket.blob(dest).upload_from_filename(local_path, content_type=content_type)
        return dest

    def upload_bytes(self, data: bytes, dest: str, content_type: str) -> str:
        self.bucket.blob(dest).upload_from_string(data, content_type=content_type)
        return dest


def get_media() -> Media:
    return Media()
