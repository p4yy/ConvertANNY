"""Characterization checks: PDF handles are closed after a job (thread-local), and media merge builds the right ffmpeg call."""
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import engine


def _pdf(path):
    import pymupdf
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "hello")
    doc.save(str(path))
    doc.close()
    return str(path)


def check_documents_are_closed_after_job():
    with tempfile.TemporaryDirectory() as d:
        path = _pdf(Path(d) / "a.pdf")
        mu = engine._mu()
        first, second = mu.open(path), mu.Document(path)
        assert not first.is_closed and not second.is_closed and first.page_count == 1
        engine.close_pdfs()
        assert first.is_closed and second.is_closed
        engine.close_pdfs()                                     # nothing left to do, must not fail
        third = engine._mu().open(path)
        third.close()                                           # already closed by the caller: still fine
        engine.close_pdfs()


def check_passthrough_attributes():
    mu = engine._mu()
    import pymupdf
    assert mu.Rect is pymupdf.Rect and mu.Matrix is pymupdf.Matrix


def check_tracking_is_per_thread():
    with tempfile.TemporaryDirectory() as d:
        path = _pdf(Path(d) / "a.pdf")
        mine = engine._mu().open(path)
        seen = {}

        def other():
            doc = engine._mu().open(path)
            engine.close_pdfs()
            seen["theirs_closed"] = doc.is_closed
            seen["mine_closed_by_them"] = mine.is_closed
        t = threading.Thread(target=other)
        t.start()
        t.join()
        assert seen == {"theirs_closed": True, "mine_closed_by_them": False}, seen
        engine.close_pdfs()
        assert mine.is_closed


def check_close_survives_a_failing_document():
    import pymupdf

    class Broken:
        is_closed = False

        def close(self):
            raise RuntimeError("boom")

    real_open = pymupdf.open
    with tempfile.TemporaryDirectory() as d:
        path = _pdf(Path(d) / "a.pdf")
        try:
            pymupdf.open = lambda *a, **k: Broken() if a == ("broken",) else real_open(*a, **k)
            bad = engine._mu().open("broken")
            good = engine._mu().open(path)
        finally:
            pymupdf.open = real_open
        assert isinstance(bad, Broken)
        engine.close_pdfs()                                     # the failure must not stop the others closing
        assert good.is_closed


def _clip(path, tone=False):
    cmd = [engine.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
           "testsrc=size=64x48:rate=10:duration=1", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
           "-shortest", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True)
    return str(path)


def check_merge_command_shape():
    seen = []
    saved = engine.run
    engine.run = lambda cmd, **kw: seen.append(list(cmd))
    try:
        v = engine.media_merge(["/x/a.mp4", "/x/b.mov", "/x/c.mkv"], {})
        a = engine.media_merge(["/x/a.flac", "/x/b.flac"], {})
        m = engine.media_merge(["/x/a.mp3", "/x/b.mp3"], {})
    finally:
        engine.run = saved
    assert v.name.endswith(" merged.mp4") and a.suffix == ".flac" and m.suffix == ".mp3"
    cmd = seen[0]
    assert cmd[1:4] == ["-hide_banner", "-loglevel", "error"] and "-y" in cmd
    assert cmd[cmd.index("-filter_complex") + 1] == "[0:v:0][0:a:0][1:v:0][1:a:0][2:v:0][2:a:0]concat=n=3:v=1:a=1[v][a]"
    assert [cmd[i + 1] for i, x in enumerate(cmd) if x == "-i"] == ["/x/a.mp4", "/x/b.mov", "/x/c.mkv"]
    tail = cmd[cmd.index("-filter_complex") + 2:]
    assert tail[:-1] == ["-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "21", "-pix_fmt", "yuv420p", "-c:a", "aac"]
    assert tail[-1] == str(v)
    acmd = seen[1]
    assert acmd[acmd.index("-filter_complex") + 1] == "[0:a:0][1:a:0]concat=n=2:v=0:a=1[a]"
    assert acmd[acmd.index("-filter_complex") + 2:-1][:2] == ["-map", "[a]"]
    assert acmd[acmd.index("-filter_complex") + 4:-1] == engine.AUDIO_ARGS["flac"][1:]
    mcmd = seen[2]
    assert mcmd[mcmd.index("-filter_complex") + 4:-1] == engine.AUDIO_ARGS["mp3"][1:]


def check_merge_really_joins_clips():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        a, b = _clip(d / "a.mp4"), _clip(d / "b.mp4")
        out = engine.media_merge([a, b], {})
        assert out.exists() and 1.8 < engine.media_duration(out) < 2.3, engine.media_duration(out)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("check_") and callable(fn):
            fn()
    print("Engine PDF session and merge passed")
