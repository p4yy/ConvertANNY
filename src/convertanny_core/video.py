"""ConvertANNY-owned video conversion orchestration over the FFmpeg codec backend."""

from __future__ import annotations

import queue
import re
import subprocess
import tempfile
import threading
from pathlib import Path

from .model import CancelToken, ConversionError
from .paths import OutputPolicy, atomic_write


VIDEO_OUTPUTS = {
    "mp4": ("mp4", ["-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"]),
    "mov": ("mov", ["-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k"]),
    "mkv": ("matroska", ["-c:v", "libx264", "-crf", "20", "-c:a", "aac", "-b:a", "192k"]),
    "mkv_hevc": ("matroska", ["-c:v", "libx265", "-preset", "medium", "-crf", "24", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-x265-params", "log-level=error"]),
    "webm": ("webm", ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "33", "-deadline", "good", "-cpu-used", "5", "-row-mt", "1", "-c:a", "libopus", "-b:a", "128k"]),
    "avi": ("avi", ["-c:v", "mpeg4", "-q:v", "4", "-c:a", "libmp3lame", "-q:a", "3"]),
    "wmv": ("asf", ["-c:v", "wmv2", "-q:v", "4", "-c:a", "wmav2", "-b:a", "192k"]),
}


def _duration(ffmpeg: str, source: Path) -> float:
    result = subprocess.run([ffmpeg, "-hide_banner", "-i", str(source)], stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=20,
                            creationflags=0x08000000 if __import__("os").name == "nt" else 0)
    match = re.search(rb"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
    return int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3)) if match else 0.0


def _run_pass(command: list[str], token: CancelToken | None) -> None:
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE,
                               creationflags=0x08000000 if __import__("os").name == "nt" else 0)
    try:
        while process.poll() is None:
            if token:
                try:
                    token.check()
                except Exception:
                    process.kill()
                    process.wait()
                    raise
            try:
                process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                pass
        error = process.stderr.read().decode("utf-8", "replace").strip() if process.stderr else ""
        if process.returncode:
            raise ConversionError(error.splitlines()[-1] if error else "Video operation failed")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        if process.stderr:
            process.stderr.close()


def compress_video_to_size(source: str | Path, megabytes: float, *, ffmpeg: str,
                           policy: OutputPolicy | None = None,
                           token: CancelToken | None = None) -> Path:
    """Encode to a requested approximate size with two-pass H.264 and atomic publishing."""
    source = Path(source)
    try:
        megabytes = float(megabytes)
    except (ValueError, TypeError) as exc:
        raise ConversionError("Choose a valid target size") from exc
    if not source.is_file() or not 1 <= megabytes <= 2048:
        raise ConversionError("Choose a video and a target size between 1 MB and 2 GB")
    duration = _duration(ffmpeg, source)
    if duration <= 0:
        raise ConversionError("Couldn't read the length of this video")
    if source.stat().st_size <= megabytes * 1024 * 1024:
        raise ConversionError("This file is already smaller than that")
    audio_kbps = 96 if megabytes >= 10 else 64
    video_kbps = int(megabytes * 8 * 1024 * 0.95 / duration - audio_kbps)
    if video_kbps < 90:
        raise ConversionError("This video is too long for that size")
    height = 1080 if video_kbps > 3500 else 720 if video_kbps > 1200 else 480 if video_kbps > 450 else 360
    scale = f"scale=-2:'min({height},ih)'"
    destination = (policy or OutputPolicy(suffix=f" {int(megabytes)}MB")).destination(source, "mp4")

    def write(temp: Path):
        with tempfile.TemporaryDirectory(prefix="convertanny-video-pass-") as temporary:
            log = str(Path(temporary) / "pass")
            common = ["-vf", scale, "-c:v", "libx264", "-preset", "medium", "-b:v", f"{video_kbps}k",
                      "-pix_fmt", "yuv420p", "-passlogfile", log]
            first = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                     *common, "-pass", "1", "-an", "-f", "mp4", "NUL" if __import__("os").name == "nt" else "/dev/null"]
            _run_pass(first, token)
            if token:
                token.check()
            second = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                      *common, "-pass", "2", "-c:a", "aac", "-b:a", f"{audio_kbps}k",
                      "-movflags", "+faststart", "-f", "mp4", str(temp)]
            _run_pass(second, token)
            if token:
                token.report(1.0)
    return atomic_write(destination, write, token)


def social_crop_video(source: str | Path, shape: str, center: float | None, *, ffmpeg: str,
                      policy: OutputPolicy | None = None, token: CancelToken | None = None,
                      detect_center=None) -> Path:
    """Reframe video to a common social aspect ratio, optionally using a subject center."""
    ratios = {"9:16": (9, 16), "1:1": (1, 1), "4:5": (4, 5), "2:3": (2, 3), "16:9": (16, 9)}
    if shape not in ratios:
        raise ConversionError("Choose a supported aspect ratio")
    try:
        center = float(center) if center is not None else None
    except (ValueError, TypeError):
        center = None
    if center is None and detect_center is not None:
        center = detect_center(source)
    center = .5 if center is None else max(0.0, min(1.0, center))
    width, height = ratios[shape]
    ratio = f"{width}/{height}"
    video_filter = (f"crop='if(gt(iw/ih,{ratio}),ih*{ratio},iw)':"
                    f"'if(gt(iw/ih,{ratio}),ih,iw/({ratio}))':"
                    f"'max(0,min(iw-ow,iw*{center:.4f}-ow/2))':'(ih-oh)/2',"
                    "scale='trunc(min(iw,1080)/2)*2':-2,setsar=1")
    return process_video(source, "mp4", ["-vf", video_filter, "-c:v", "libx264", "-crf", "21",
                          "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                          "-movflags", "+faststart"], ffmpeg=ffmpeg, suffix=f" {shape.replace(':', 'x')}",
                         policy=policy or OutputPolicy(suffix=f" {shape.replace(':', 'x')}"),
                         token=token)


def convert_video(source: str | Path, target_format: str, *, ffmpeg: str,
                  policy: OutputPolicy | None = None,
                  token: CancelToken | None = None) -> Path:
    """Convert video with bounded progress updates, cancellation and atomic output."""
    source = Path(source)
    key = target_format.lower().lstrip(".")
    try:
        muxer, arguments = VIDEO_OUTPUTS[key]
    except KeyError as exc:
        raise ConversionError(f"Unsupported video output: {target_format}") from exc
    extension = "mkv" if key == "mkv_hevc" else key
    suffix = " hevc" if key == "mkv_hevc" else ""
    if not source.is_file():
        raise ConversionError(f"File not found: {source}")
    if token:
        token.check()
    duration = _duration(ffmpeg, source)
    destination = (policy or OutputPolicy(suffix=suffix)).destination(source, extension)

    def write(temp: Path):
        command = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                   "-progress", "pipe:1", "-nostats", "-i", str(source),
                   "-map", "0:v:0?", "-map", "0:a:0?", "-sn", "-dn", *arguments,
                   "-f", muxer, str(temp)]
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, creationflags=0x08000000 if __import__("os").name == "nt" else 0)
        updates: queue.Queue[bytes | None] = queue.Queue()
        def read_progress():
            try:
                for line in iter(process.stdout.readline, b""):
                    updates.put(line)
            finally:
                updates.put(None)
        reader = threading.Thread(target=read_progress, daemon=True)
        reader.start()
        try:
            last = 0.0
            while process.poll() is None:
                if token:
                    try:
                        token.check()
                    except Exception:
                        process.kill()
                        process.wait()
                        raise
                try:
                    line = updates.get(timeout=0.1)
                except queue.Empty:
                    continue
                if line and line.startswith(b"out_time_ms=") and duration > 0 and token:
                    try:
                        fraction = min(0.99, int(line.split(b"=", 1)[1]) / 1_000_000 / duration)
                        if fraction > last:
                            token.report(fraction)
                            last = fraction
                    except ValueError:
                        pass
            reader.join(timeout=1)
            error = process.stderr.read().decode("utf-8", "replace").strip() if process.stderr else ""
            if process.returncode:
                raise ConversionError(error.splitlines()[-1] if error else "Video conversion failed")
            if token:
                token.report(1.0)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            if process.stdout:
                process.stdout.close()
            if process.stderr:
                process.stderr.close()

    return atomic_write(destination, write, token)


def process_video(source: str | Path, extension: str, arguments: list[str], *, ffmpeg: str,
                  suffix: str, policy: OutputPolicy | None = None,
                  before_input: list[str] | None = None,
                  token: CancelToken | None = None) -> Path:
    """Run a validated ConvertANNY video action and publish its result atomically."""
    source = Path(source)
    extension = extension.lower().lstrip(".")
    if extension not in ("mp4", "mov", "mkv", "webm", "avi", "wmv", "gif", "png", "jpg"):
        raise ConversionError(f"Unsupported video output: {extension}")
    if not source.is_file():
        raise ConversionError(f"File not found: {source}")
    muxers = {"mp4": "mp4", "mov": "mov", "mkv": "matroska", "webm": "webm",
              "avi": "avi", "wmv": "asf", "gif": "gif", "png": "image2", "jpg": "image2"}
    destination = (policy or OutputPolicy(suffix=suffix)).destination(source, extension)
    duration = _duration(ffmpeg, source)

    def write(temp: Path):
        command = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                   "-progress", "pipe:1", "-nostats", *(before_input or []), "-i", str(source),
                   *arguments, "-f", muxers[extension], str(temp)]
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, creationflags=0x08000000 if __import__("os").name == "nt" else 0)
        updates: queue.Queue[bytes | None] = queue.Queue()
        def read_progress():
            try:
                for line in iter(process.stdout.readline, b""):
                    updates.put(line)
            finally:
                updates.put(None)
        reader = threading.Thread(target=read_progress, daemon=True)
        reader.start()
        last = 0.0
        try:
            while process.poll() is None:
                if token:
                    try:
                        token.check()
                    except Exception:
                        process.kill()
                        process.wait()
                        raise
                try:
                    line = updates.get(timeout=0.1)
                except queue.Empty:
                    continue
                if line and line.startswith(b"out_time_ms=") and duration > 0 and token:
                    try:
                        fraction = min(0.99, int(line.split(b"=", 1)[1]) / 1_000_000 / duration)
                        if fraction > last:
                            token.report(fraction)
                            last = fraction
                    except ValueError:
                        pass
            reader.join(timeout=1)
            error = process.stderr.read().decode("utf-8", "replace").strip() if process.stderr else ""
            if process.returncode:
                raise ConversionError(error.splitlines()[-1] if error else "Video operation failed")
            if token:
                token.report(1.0)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            if process.stdout:
                process.stdout.close()
            if process.stderr:
                process.stderr.close()
    return atomic_write(destination, write, token)
