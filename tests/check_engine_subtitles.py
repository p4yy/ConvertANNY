"""Characterization checks for the engine's subtitle helpers (side files, language tags, mux, list, extract, burn).

They run against real ffmpeg on a one-second synthetic clip, so they pin what users get on disk.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import engine

SRT_EN = "1\n00:00:00,000 --> 00:00:00,800\nHello there\n\n"
SRT_AR = "1\n00:00:00,000 --> 00:00:00,800\nمرحبا بالعالم\n\n"


def _clip(folder: Path, name="movie.mp4") -> Path:
    out = folder / name
    subprocess.run([engine.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc=size=160x120:rate=10:duration=1", "-pix_fmt", "yuv420p", str(out)], check=True)
    return out


def check_side_files():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        for n in ("movie.mp4", "movie.ar.srt", "Movie.en.ass", "movie.vtt", "other.srt", "movie.txt", "movie.sub"):
            (d / n).write_text("x")
        got = engine._side_subtitles(d / "movie.mp4")
        assert got == sorted(str(d / n) for n in ("Movie.en.ass", "movie.ar.srt", "movie.vtt")), got
    assert engine._side_subtitles(Path("/definitely/not/here/movie.mp4")) == []


def check_filter_path_quoting():
    assert engine._ff_filter_path("C:\\a b\\it's.srt").endswith("a b/it\\'s.srt")
    assert engine._ff_filter_path("C:/x/y.srt").startswith("C\\:/x/y.srt")
    assert "\\\\" not in engine._ff_filter_path("a/b/c.srt")


def check_language_guess():
    f = engine._sub_language
    assert f("movie.ar.srt", "") == "ara"
    assert f("movie.English.srt", "") == "eng"
    assert f("movie_fr.srt", "") == "fre"
    assert f("my-film.zho.vtt", "") == "chi"
    assert f("movie.srt", "hello world") is None
    assert f("movie.srt", "مرحبا بالعالم كله") == "ara"
    assert f("movie.srt", "ab " + "ب" * 3) == "ara"           # Arabic letters outnumber Latin ones
    assert f("movie.srt", "hello مرحبا") is None               # not a majority
    assert f("ar.srt", "") is None                              # the first part is the name, not a tag
    assert f("movie.xx.ar.srt", "") == "ara"                    # the last recognised tag wins
    assert f("movie.ar.xx.srt", "") == "ara"
    assert f("movie.srt", "1234 --> 5678") is None


def check_errors_without_subs():
    with tempfile.TemporaryDirectory() as d:
        v = _clip(Path(d))
        for fn in (engine.mux_subtitles, engine.burn_subtitles):
            try:
                fn([str(v)], {})
            except engine.ConversionError as exc:
                assert str(exc) == "No subtitle file found"
            else:
                raise AssertionError(fn.__name__)
        try:
            engine.extract_subtitles(str(v), {})
        except engine.ConversionError as exc:
            assert str(exc) == "No subtitles inside this video"
        else:
            raise AssertionError("extract")
        assert engine.subtitle_streams(str(Path(d) / "gone.mp4")) == []


def check_mux_list_extract_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        v = _clip(d)
        (d / "movie.ar.srt").write_text(SRT_AR, encoding="utf-8")
        (d / "movie.en.srt").write_text(SRT_EN, encoding="utf-8-sig")
        out = engine.mux_subtitles([str(v)], {})
        assert out == d / "movie subtitles.mkv" and out.exists(), out
        tracks = engine.subtitle_streams(str(out))
        assert [(t["index"], t["lang"], t["codec"], t["text"]) for t in tracks] == \
            [(0, "ara", "subrip", True), (1, "eng", "subrip", True)], tracks
        assert [t["title"] for t in tracks] == ["Arabic", "English"], tracks
        assert engine.subtitle_streams(str(out)) is engine.subtitle_streams(str(out))      # cached per file+mtime
        # a second pass keeps the earlier tracks and puts the new one first
        (d / "movie subtitles.ru.srt").write_text(SRT_EN, encoding="utf-8")
        again = engine.mux_subtitles([str(out)], {})
        assert again.exists() and again != out
        assert len(engine.subtitle_streams(str(again))) == 3
        outs = engine.extract_subtitles(str(out), {})
        assert sorted(p.name for p in outs) == ["movie subtitles.ara.srt", "movie subtitles.eng.srt"], outs
        assert "مرحبا" in outs[0].read_text(encoding="utf-8") or "مرحبا" in outs[1].read_text(encoding="utf-8")


def check_mux_explicit_files_and_cp1256():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        v = _clip(d)
        sub = d / "picked.srt"
        sub.write_bytes(SRT_AR.encode("cp1256"))
        out = engine.mux_subtitles([str(v), str(sub)], {})
        tr = engine.subtitle_streams(str(out))
        assert len(tr) == 1 and tr[0]["lang"] == "ara", tr          # decoded from Windows-1256, tagged by its letters
        assert tr[0]["title"] == "Arabic"


def check_burn():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        v = _clip(d)
        (d / "movie.srt").write_text(SRT_EN, encoding="utf-8")
        out = engine.burn_subtitles([str(v)], {})
        assert out == d / "movie subtitled.mp4" and out.stat().st_size > 0, out


def check_picture_subtitles_are_refused():
    saved = engine.subtitle_streams
    try:
        engine.subtitle_streams = lambda src: [{"index": 0, "lang": "eng", "codec": "dvd_subtitle", "title": "", "text": False}]
        try:
            engine.extract_subtitles("x.mkv", {})
        except engine.ConversionError as exc:
            assert "pictures" in str(exc)
        else:
            raise AssertionError("expected refusal")
    finally:
        engine.subtitle_streams = saved


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("check_") and callable(fn):
            fn()
    print("Engine subtitle helpers passed")
