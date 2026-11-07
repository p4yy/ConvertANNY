"""Encoder presets, clock-text parsing and single-frame grabbing for ConvertANNY's video tools."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Mapping, Sequence

# Each preset says what to ask ffmpeg for; `encoder_args` turns it into the actual option list.
HEVC_MP4 = {"video": "libx265", "preset": "medium", "crf": 26, "tag": "hvc1",
            "audio": "aac", "audio_rate": "160k", "extra": ("-x265-params", "log-level=error")}
SMALL_MP4 = {"video": "libx264", "preset": "slow", "crf": 28,
             "audio": "aac", "audio_rate": "96k", "extra": ()}


def encoder_args(preset: Mapping) -> list[str]:
    """Option list for an MP4 preset: video codec/quality, pixel format, optional tag, audio, fast-start."""
    out = ["-c:v", preset["video"], "-preset", preset["preset"], "-crf", str(preset["crf"]),
           "-pix_fmt", "yuv420p"]
    if preset.get("tag"):
        out += ["-tag:v", preset["tag"]]
    out += ["-c:a", preset["audio"], "-b:a", preset["audio_rate"], "-movflags", "+faststart"]
    out += list(preset.get("extra", ()))
    return out


def clock_to_seconds(text: str) -> float:
    """Seconds in a validated clock string such as '90', '1:30' or '01:01:30.5'."""
    total = 0.0
    for field in str(text).strip().split(":"):
        total = total * 60 + float(field)
    return total


def grab_frame(ffmpeg: str, src, out, at: float, width: int = 640, timeout: int = 60,
               creationflags: int = 0) -> bool:
    """Write one frame of `src`, taken `at` seconds in and scaled to `width` px wide, to `out`."""
    argv: Sequence[str] = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{at:.2f}",
                           "-i", str(src), "-frames:v", "1", "-vf", f"scale={width}:-2", str(out)]
    done = subprocess.run(list(argv), capture_output=True, stdin=subprocess.DEVNULL,
                          creationflags=creationflags, timeout=timeout)
    return done.returncode == 0 and Path(out).exists()
