"""Pins the ffmpeg command lines and time handling of the small video helpers in the engine.

Written against the pre-rewrite code; the rewrite must keep every assertion true.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import engine


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, cmd, *a, **kw):
        self.calls.append(list(cmd))
        return None


def _with_patched_run(fn):
    rec = _Recorder()
    saved = engine.run, engine.ffmpeg, engine._token
    engine.run, engine.ffmpeg, engine._token = rec, (lambda: "FFMPEG"), (lambda: None)
    try:
        fn()
    finally:
        engine.run, engine.ffmpeg, engine._token = saved
    return rec.calls


def check_hevc_command():
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "clip.mov"
        src.write_bytes(b"x")
        calls = _with_patched_run(lambda: engine.video_to_hevc(src, {}))
        assert len(calls) == 1
        cmd = calls[0]
        assert cmd[:5] == ["FFMPEG", "-hide_banner", "-loglevel", "error", "-y"]
        assert cmd[5:7] == ["-i", str(src)]
        assert cmd[7:] == ["-c:v", "libx265", "-preset", "medium", "-crf", "26", "-pix_fmt", "yuv420p",
                           "-tag:v", "hvc1", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
                           "-x265-params", "log-level=error", str(Path(d) / "clip hevc.mp4")], cmd[7:]


def check_compress_automatic_command():
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "clip.mkv"
        src.write_bytes(b"x")
        for params in ({}, {"Target size": "Automatic"}, {"Target size": ""}):
            calls = _with_patched_run(lambda: engine.video_compress(src, params))
            assert len(calls) == 1, params
            assert calls[0][5:] == ["-i", str(src), "-c:v", "libx264", "-preset", "slow", "-crf", "28",
                                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", "-movflags",
                                    "+faststart", str(Path(d) / "clip compressed.mp4")], calls[0]


def check_compress_target_delegates():
    seen = []
    saved = engine.video_to_size
    engine.video_to_size = lambda src, p: seen.append((src, dict(p))) or "done"
    try:
        assert engine.video_compress("a.mp4", {"Target size": "25 MB"}) == "done"
    finally:
        engine.video_to_size = saved
    assert seen == [("a.mp4", {"Target size": "25 MB"})], seen


def check_preview_frame():
    import subprocess
    captured = {}
    saved = (subprocess.run, engine.ffmpeg, engine.media_duration)

    def fake_run(cmd, **kw):
        captured["cmd"], captured["kw"] = list(cmd), kw
        Path(cmd[-1]).write_bytes(b"png")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "p.png"
        subprocess.run, engine.ffmpeg, engine.media_duration = fake_run, (lambda: "FFMPEG"), (lambda s: 100.0)
        try:
            assert engine.preview_frame("v.mp4", out) is True
            assert captured["cmd"] == ["FFMPEG", "-hide_banner", "-loglevel", "error", "-y", "-ss", "40.00",
                                       "-i", "v.mp4", "-frames:v", "1", "-vf", "scale=640:-2", str(out)]
            assert captured["kw"]["timeout"] == 60
            assert captured["kw"]["stdin"] == subprocess.DEVNULL
            # unknown duration -> seek 0.00
            engine.media_duration = lambda s: None
            out.unlink()
            assert engine.preview_frame("v.mp4", out) is True
            assert captured["cmd"][6] == "0.00"
            # failing ffmpeg -> False even if a stale file exists
            subprocess.run = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, b"", b"")
            assert engine.preview_frame("v.mp4", out) is False
            # ffmpeg ok but nothing written -> False
            out.unlink()
            subprocess.run = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, b"", b"")
            assert engine.preview_frame("v.mp4", out) is False
        finally:
            subprocess.run, engine.ffmpeg, engine.media_duration = saved


def check_gif_clip_times():
    seen = []
    saved = engine._owned_process_video, engine.ffmpeg, engine._token
    engine._owned_process_video = lambda src, ext, args, **kw: seen.append((ext, list(args), kw["before_input"])) or "ok"
    engine.ffmpeg, engine._token = (lambda: "FFMPEG"), (lambda: None)
    try:
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "v.mp4"
            src.write_bytes(b"x")
            engine.video_gif_clip(src, {"Start": "1:30", "End": "01:01:30.5"})
            engine.video_gif_clip(src, {})
            engine.video_gif_clip(src, {"Start": "2", "End": "9"})
            for bad in ({"Start": "5", "End": "5"}, {"Start": "10", "End": "3"}):
                try:
                    engine.video_gif_clip(src, bad)
                except engine.ConversionError as exc:
                    assert str(exc) == "End must be after Start"
                else:
                    raise AssertionError(bad)
            try:
                engine.video_gif_clip(src, {"Start": "x"})
            except engine.ConversionError as exc:
                assert "Invalid time" in str(exc)
            else:
                raise AssertionError("bad time accepted")
    finally:
        engine._owned_process_video, engine.ffmpeg, engine._token = saved
    assert seen[0][2] == ["-ss", "90.000"] and seen[0][1][:2] == ["-t", "3600.500"], seen[0]
    assert seen[1][2] == ["-ss", "0.000"] and seen[1][1][:2] == ["-t", "5.000"], seen[1]
    assert seen[2][2] == ["-ss", "2.000"] and seen[2][1][:2] == ["-t", "7.000"], seen[2]
    assert seen[0][1][2] == "-vf" and seen[0][1][-2:] == ["-loop", "0"]


def check_link_log_is_best_effort():
    import types
    logged = []
    saved = sys.modules.get("winsys")
    sys.modules["winsys"] = types.SimpleNamespace(log=logged.append)
    try:
        engine._link_log("hello")
        assert logged == ["hello"]
        sys.modules["winsys"] = types.SimpleNamespace(log=lambda m: 1 / 0)
        engine._link_log("never raises")
    finally:
        if saved is None:
            sys.modules.pop("winsys", None)
        else:
            sys.modules["winsys"] = saved


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("check_"):
            fn()
            print("ok", name)
