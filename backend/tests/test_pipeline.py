from app.media import burn_args, cut_args, to_srt
from app.pipeline import apply_revisions, clamp_selection
from app.schemas import CultureReport, Revision, Selection, SubtitleLine


def test_clamp_selection_limits_length_and_bounds():
    sel = clamp_selection(Selection(start=-5, end=500, reason="r"), duration=300, max_seconds=30)
    assert (sel.start, sel.end) == (0, 30)

    sel = clamp_selection(Selection(start=298, end=299, reason="r"), duration=300, max_seconds=30)
    assert (sel.start, sel.end) == (295, 300)


def test_to_srt():
    lines = [SubtitleLine(start=1.25, end=3.5, original="Hi", translated="Olá")]
    assert to_srt(lines) == "1\n00:00:01,250 --> 00:00:03,500\nOlá\n"


def test_apply_revisions_ignores_bad_indexes():
    lines = [SubtitleLine(start=0, end=1, original="a", translated="b")]
    report = CultureReport(
        verdict="ready",
        summary="",
        issues=[],
        revisions=[Revision(index=0, translated="c"), Revision(index=9, translated="x")],
        caption="",
        hashtags=[],
        thumbnail_title="",
        highlight_time=0,
    )
    assert [x.translated for x in apply_revisions(lines, report)] == ["c"]
    assert lines[0].translated == "b"  # Original untouched


def test_ffmpeg_args():
    args = cut_args("https://src", 10, 40, "out.mp4", vertical=True)
    assert args[args.index("-ss") + 1] == "10.00"
    assert args[args.index("-t") + 1] == "30.00"
    assert "-filter_complex" in args
    assert "-filter_complex" not in cut_args("https://src", 10, 40, "out.mp4", vertical=False)
    args = burn_args("in.mp4", "/tmp/s.srt", "out.mp4")
    assert args[args.index("-vf") + 1].startswith("subtitles=/tmp/s.srt")


def test_schema_uses_camel_case():
    sel = Selection(start=1, end=2, reason="r")
    assert "start" in sel.model_dump(by_alias=True)
    report_fields = CultureReport.model_json_schema()["properties"]
    assert "thumbnailTitle" in report_fields


def test_normalize_index_rescales_overshooting_timeline():
    from app.pipeline import normalize_index
    from app.schemas import Scene, SceneIndex

    def scene(start, end):
        return Scene(start=start, end=end, description="", dialogue="", characters=[], mood="")

    stretched = SceneIndex(scenes=[scene(0, 600), scene(600, 1200)])
    fixed = normalize_index(stretched, duration=600)
    assert [(s.start, s.end) for s in fixed.scenes] == [(0, 300), (300, 600)]

    # End before start (seen in real output) is clamped instead of rescaled.
    odd = normalize_index(SceneIndex(scenes=[scene(0, 300), scene(590, 469)]), duration=600)
    assert [(s.start, s.end) for s in odd.scenes] == [(0, 300), (590, 590)]


def test_hashtags_are_normalized():
    from app.pipeline import hashtags

    assert hashtags(["anime", "#Gamer BR", " ", "#"]) == ["#anime", "#GamerBR"]


def _line(start, end, text="x"):
    return SubtitleLine(start=start, end=end, original=text, translated=text)


def test_align_selection_snaps_to_nearest_dialogue():
    from app.pipeline import align_selection

    sel = Selection(start=100, end=120, reason="r")
    # Overlapping dialogue: keep as is.
    assert align_selection(sel, [_line(110, 112)], duration=300) is sel
    # Dialogue only before the clip: move the clip onto it, keeping the length.
    moved = align_selection(sel, [_line(85, 88), _line(30, 31)], duration=300)
    assert (moved.start, moved.end) == (84.5, 104.5)
    # No dialogue at all: keep as is.
    assert align_selection(sel, [], duration=300) is sel


def test_lines_in_returns_clip_relative_lines():
    from app.pipeline import lines_in

    sel = Selection(start=100, end=120, reason="r")
    lines = [_line(95, 101, "a"), _line(110, 125, "b"), _line(130, 131, "c")]
    assert [(x.original, x.start, x.end) for x in lines_in(lines, sel)] == [
        ("a", 0, 1),
        ("b", 10, 20),
    ]
