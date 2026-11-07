"""Behavioural checks for the engine's naming, classification, time, progress and cancellation helpers.

These pin the contract the rest of the app relies on, so the helpers can be
rewritten without changing what users see on disk or in progress bars.
"""
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import engine
from convertanny_core.processes import DesktopCancelToken


def check_ext_and_category():
    cases = {
        "a/b/Photo.JPG": "jpg", "x.tar.gz": "tgz", "X.TAR.BZ2": "tbz2", "y.tar.xz": "txz",
        "z.tbz": "tbz2", "noext": "", ".hidden": "", "weird.name.PDF": "pdf", "arch.tgz": "tgz",
    }
    for name, want in cases.items():
        assert engine.ext_of(name) == want, (name, engine.ext_of(name), want)
    assert engine.ext_of(Path("C:/dir/clip.MP4")) == "mp4"
    with tempfile.TemporaryDirectory() as d:
        assert engine.category_of([str(Path(d))]) == "folder"
        assert engine.category_of(["a.png", "b.JPEG"]) == "image"
        assert engine.category_of(["a.png", "b.mp3"]) == "mixed"
        assert engine.category_of(["a.unknownext"]) == "other"
        assert engine.category_of([str(Path(d)), "a.png"]) == "mixed"
        assert engine.category_of([]) == "mixed"


def check_errors():
    assert issubclass(engine.ConversionError, Exception)
    assert issubclass(engine.Cancelled, Exception)
    for kind in (engine.ConversionError, engine.Cancelled):
        try:
            raise kind("boom")
        except kind as exc:
            assert str(exc) == "boom"


def check_parse_and_secs():
    for ok in ("90", "1:30", "00:01:30.5", " 12 "):
        assert engine.parse_time(ok) == ok.strip()
    for bad in ("", "1;30", "abc", "-5", "1:3x", "1 2"):
        try:
            engine.parse_time(bad)
        except engine.ConversionError as exc:
            assert "Invalid time" in str(exc)
        else:
            raise AssertionError(f"parse_time accepted {bad!r}")
    assert engine._secs("90") == 90.0
    assert engine._secs("1:30") == 90.0
    assert engine._secs("01:01:01.5") == 3661.5
    assert engine._secs(" 2:00 ") == 120.0
    assert engine._secs("junk") == 0.0
    assert engine._secs("") == 0.0
    assert engine._secs(None) == 0.0


def check_unique_and_outputs():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        assert engine.unique_path(root / "new.txt") == root / "new.txt"
        (root / "a.txt").write_text("x")
        assert engine.unique_path(root / "a.txt") == root / "a (2).txt"
        (root / "a (2).txt").write_text("x")
        assert engine.unique_path(root / "a.txt") == root / "a (3).txt"
        (root / "pack.tar.gz").write_text("x")
        assert engine.unique_path(root / "pack.tar.gz") == root / "pack (2).tar.gz"
        (root / "PACK2.TAR.BZ2").write_text("x")
        assert engine.unique_path(root / "PACK2.TAR.BZ2") == root / "PACK2 (2).TAR.BZ2"
        (root / "bare").write_text("x")
        assert engine.unique_path(root / "bare") == root / "bare (2)"
        (root / "c.png").write_text("x")
        assert engine.out_for(root / "c.png", "jpg") == root / "c.jpg"
        assert engine.out_for(root / "c.png", "png") == root / "c (2).png"
        assert engine.out_for(root / "c.png", "webp", "small") == root / "c small.webp"
        assert engine.out_for(root / "pack.tar.gz", "zip") == root / "pack.zip"
        (root / "c folder").mkdir()
        assert engine.out_dir_for(root / "c.png", "folder") == root / "c folder (2)"
        assert engine.out_dir_for(root / "c.png", "pages") == root / "c pages"
        other = root / "elsewhere"
        other.mkdir()
        old = engine.OUTPUT_DIR
        try:
            engine.OUTPUT_DIR = str(other)
            assert engine._target_dir(root / "c.png") == other
            assert engine.out_for(root / "c.png", "gif") == other / "c.gif"
            engine.OUTPUT_DIR = str(root / "missing")
            assert engine._target_dir(root / "c.png") == root
            engine.OUTPUT_DIR = None
            assert engine._target_dir(root / "c.png") == root
        finally:
            engine.OUTPUT_DIR = old


def check_token_progress_and_cancel():
    assert engine._token() is None
    engine.check_cancel()                       # no token: never raises
    engine.report_progress(0.5)                 # no token: silent
    events = []
    token = DesktopCancelToken()
    token.on_path = lambda kind, value: events.append((kind, value))
    token.batch = (1, 4)
    engine._ctx.token = token
    try:
        engine.report_progress(0.5)
        engine.report_progress(2.0)
        engine.report_progress(-1.0)
        assert events == [("progress", "0.3750"), ("progress", "0.5000"), ("progress", "0.2500")], events
        events.clear()
        explicit = DesktopCancelToken()
        explicit.on_path = lambda kind, value: events.append((kind, value))
        engine.report_progress(0.25, explicit)
        assert events == [("progress", "0.2500")], events
        # a failing callback must never break the job
        token.on_path = lambda *_: (_ for _ in ()).throw(RuntimeError("ui gone"))
        engine.report_progress(0.1)
        # remember: outputs are tracked, temp paths are reported but not tracked
        seen = []
        token.on_path = lambda kind, value: seen.append((kind, value))
        out = engine._remember(Path("out.bin"))
        tmp = engine._remember(Path("scratch"), "tmp")
        assert out == Path("out.bin") and tmp == Path("scratch")
        assert token.paths == [Path("out.bin")]
        assert seen == [("out", "out.bin"), ("tmp", "scratch")]
        token.on_path = lambda *_: (_ for _ in ()).throw(RuntimeError("ui gone"))
        engine._remember(Path("again.bin"))
        assert token.paths[-1] == Path("again.bin")
        engine.check_cancel()
        token.cancel()
        try:
            engine.check_cancel()
        except engine.Cancelled:
            pass
        else:
            raise AssertionError("cancelled token did not raise")
    finally:
        engine._ctx.token = None
    # the token is per thread
    other = []
    engine._ctx.token = token
    worker = threading.Thread(target=lambda: other.append(engine._token()))
    worker.start(); worker.join()
    engine._ctx.token = None
    assert other == [None]


def check_ffmpeg_lookup():
    saved = engine._FFMPEG
    try:
        engine._FFMPEG = "cached-ffmpeg"
        assert engine.ffmpeg() == "cached-ffmpeg"
        engine._FFMPEG = None
        found = engine.ffmpeg()
        assert found and engine._FFMPEG == found
    finally:
        engine._FFMPEG = saved


def check_duration_and_expected():
    saved = dict(engine._DURATIONS)
    try:
        engine._DURATIONS["clip.mp4"] = 100.0
        assert engine.media_duration("clip.mp4") == 100.0
        assert engine._expected_seconds("clip.mp4", ["-t", "10"], ()) == 10.0
        assert engine._expected_seconds("clip.mp4", [], ()) == 100.0
        assert engine._expected_seconds("clip.mp4", [], ("-ss", "20")) == 80.0
        assert engine._expected_seconds("clip.mp4", ["-to", "30"], ("-ss", "10")) == 30.0
        assert engine._expected_seconds("clip.mp4", ["-to", "200"], ("-ss", "10")) == 90.0
        assert engine._expected_seconds("clip.mp4", ["-t"], ()) == 100.0   # dangling flag is ignored
        assert engine._expected_seconds("clip.mp4", ["-to", "30"], ()) == 30.0
        assert engine._expected_seconds("clip.mp4", ["-vf", "setpts=0.5*PTS"], ()) == 50.0
        assert engine._expected_seconds("clip.mp4", [], ("-ss", "500")) == 0.0
        engine._DURATIONS["pic.png"] = 9.0
        assert engine._expected_seconds("pic.png", [], ()) == 0.0
        assert engine._expected_seconds("pic.png", ["-to", "5"], ()) == 5.0
    finally:
        engine._DURATIONS.clear(); engine._DURATIONS.update(saved)


def main():
    for fn in (check_ext_and_category, check_errors, check_parse_and_secs, check_unique_and_outputs,
               check_token_progress_and_cancel, check_ffmpeg_lookup, check_duration_and_expected):
        fn()
    print("Engine naming, classification, time, progress and cancellation helpers passed")


if __name__ == "__main__":
    main()
