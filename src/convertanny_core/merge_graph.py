"""ffmpeg arguments for joining several media files end to end."""
from __future__ import annotations

from typing import Sequence


def input_args(paths: Sequence) -> list[str]:
    return [arg for path in paths for arg in ("-i", str(path))]


def concat_graph(count: int, with_video: bool) -> str:
    """A concat filter over `count` inputs, taking video+audio or audio only from each."""
    pads = "".join(f"[{n}:v:0][{n}:a:0]" if with_video else f"[{n}:a:0]" for n in range(count))
    return f"{pads}concat=n={count}:v={int(with_video)}:a=1" + ("[v][a]" if with_video else "[a]")


VIDEO_ENCODE = ["-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "21", "-pix_fmt", "yuv420p", "-c:a", "aac"]


def audio_encode(codec_args: Sequence[str]) -> list[str]:
    return ["-map", "[a]", *codec_args]
