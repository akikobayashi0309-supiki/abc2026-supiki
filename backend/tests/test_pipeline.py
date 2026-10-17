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

    ok = SceneIndex(scenes=[scene(0, 590)])
    assert normalize_index(ok, duration=600) is ok


def test_hashtags_are_normalized():
    from app.pipeline import hashtags

    assert hashtags(["anime", "#Gamer BR", " ", "#"]) == ["#anime", "#GamerBR"]
