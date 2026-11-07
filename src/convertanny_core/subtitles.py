"""ConvertANNY-authored SRT and WebVTT text transformations."""

from __future__ import annotations

import re
import html
from pathlib import Path

from .model import ConversionError
from .paths import OutputPolicy, atomic_write

_TIME = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2})[,.](\d{1,3})$")
_ASS_TIME = re.compile(r"^(\d+):(\d{2}):(\d{2})[.](\d{1,2})$")


def _read(source: Path) -> str:
    data = source.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return data.decode(encoding).replace("\r\n", "\n").replace("\r", "\n")
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def srt_to_vtt(source: str | Path, *, directory=None) -> Path:
    source = Path(source)
    text = _read(source).lstrip("\ufeff")
    text = re.sub(r"(?m)(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", text)
    destination = OutputPolicy(directory=Path(directory) if directory else None).destination(source, "vtt")
    return atomic_write(destination, lambda temp: temp.write_text("WEBVTT\n\n" + text.strip() + "\n", encoding="utf-8"))


def vtt_to_srt(source: str | Path, *, directory=None) -> Path:
    source = Path(source)
    text = re.sub(r"^WEBVTT[^\n]*(?:\n|$)", "", _read(source).lstrip("\ufeff"), count=1)
    cues = [cue for cue in re.split(r"\n{2,}", text.strip()) if "-->" in cue]
    if not cues:
        raise ConversionError("No WebVTT cues were found")
    output = []
    for index, cue in enumerate(cues, 1):
        lines = cue.splitlines()
        while lines and "-->" not in lines[0]:
            lines.pop(0)
        if not lines:
            continue
        timing = re.sub(r"(?<![\d:])(\d{2}:\d{2})\.(\d{3})", r"00:\1,\2", lines[0])
        timing = re.sub(r"(\d{2}:\d{2}:\d{2})\.(\d{3})", r"\1,\2", timing)
        timing = re.sub(r"\s+(align|line|position|size|vertical):\S+", "", timing)
        output.append(f"{index}\n{timing}\n" + "\n".join(lines[1:]))
    if not output:
        raise ConversionError("No valid WebVTT cues were found")
    destination = OutputPolicy(directory=Path(directory) if directory else None).destination(source, "srt")
    return atomic_write(destination, lambda temp: temp.write_text("\n\n".join(output) + "\n", encoding="utf-8"))


def _timestamp(value: str) -> int:
    match = _TIME.match(value.strip())
    if not match:
        raise ConversionError(f"Invalid subtitle timestamp: {value}")
    hours, minutes, seconds, fraction = match.groups()
    milliseconds = int(fraction.ljust(3, "0")[:3])
    return (((int(hours or 0) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + milliseconds)


def _ass_timestamp(value: str) -> int:
    match = _ASS_TIME.match(value.strip())
    if not match:
        raise ConversionError(f"Invalid ASS timestamp: {value}")
    hours, minutes, seconds, centiseconds = match.groups()
    return (((int(hours) * 60 + int(minutes)) * 60 + int(seconds)) * 1000
            + int(centiseconds.ljust(2, "0")) * 10)


def _format_time(milliseconds: int, separator: str = ",") -> str:
    milliseconds = max(0, milliseconds)
    seconds, fraction = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}{separator}{fraction:03}"


def _parse_srt_vtt(text: str):
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cues, index = [], 0
    while index < len(lines):
        match = re.search(r"(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}|\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*"
                          r"(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}|\d{2}:\d{2}[,.]\d{1,3})", lines[index])
        if not match:
            index += 1
            continue
        start = _timestamp(match.group(1))
        end = _timestamp(match.group(2))
        index += 1
        body = []
        while index < len(lines) and lines[index].strip():
            body.append(lines[index])
            index += 1
        if end < start:
            raise ConversionError("A subtitle cue ends before it starts")
        cues.append((start, end, "\n".join(body)))
    return cues


def _parse_ass(text: str):
    section = ""
    columns = None
    cues = []
    for line in text.replace("\r", "").split("\n"):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped.casefold()
        elif section == "[events]" and stripped.casefold().startswith("format:"):
            columns = [item.strip().casefold() for item in stripped.split(":", 1)[1].split(",")]
        elif section == "[events]" and stripped.casefold().startswith("dialogue:"):
            if not columns:
                columns = ["layer", "start", "end", "style", "name", "marginl", "marginr", "marginv", "effect", "text"]
            parts = stripped.split(":", 1)[1].lstrip().split(",", len(columns) - 1)
            if len(parts) != len(columns):
                continue
            row = dict(zip(columns, parts))
            try:
                start, end = _ass_timestamp(row["start"]), _ass_timestamp(row["end"])
            except (KeyError, ConversionError):
                continue
            body = row.get("text", "").replace(r"\N", "\n").replace(r"\n", "\n").replace(r"\h", " ")
            body = re.sub(r"\{[^}]*\}", "", body)
            cues.append((start, end, body))
    return cues


def _read_cues(source: Path):
    text = _read(source)
    if source.suffix.lower() in (".ass", ".ssa"):
        return _parse_ass(text)
    return _parse_srt_vtt(text)


def _to_ass_time(milliseconds: int) -> str:
    centiseconds = max(0, milliseconds) // 10
    seconds, fraction = divmod(centiseconds, 100)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02}:{seconds:02}.{fraction:02}"


def _to_ass(cues, *, ssa: bool = False) -> str:
    version = "[V4 Styles]" if ssa else "[V4+ Styles]"
    style_format = ("Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, TertiaryColour, BackColour, "
                    "Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding")
    style = "Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,1,1,0,2,10,10,10,1"
    event_format = "Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
    lines = ["[Script Info]", "ScriptType: v4.00" + ("" if ssa else "+"), "WrapStyle: 2", "ScaledBorderAndShadow: yes",
             "", version, "Format: " + style_format, "Style: " + style, "", "[Events]", "Format: " + event_format]
    for start, end, body in cues:
        text = body.replace("\r", "").replace("\n", r"\N")
        lines.append(f"Dialogue: 0,{_to_ass_time(start)},{_to_ass_time(end)},Default,,0,0,0,,{text}")
    return "\n".join(lines) + "\n"


def convert_subtitle(source: str | Path, target_format: str, *, directory=None) -> Path:
    source = Path(source)
    target_format = target_format.lower().lstrip(".")
    if target_format not in {"srt", "vtt", "ass"}:
        raise ConversionError(f"Unsupported subtitle format: {target_format}")
    cues = _read_cues(source)
    if not cues:
        raise ConversionError("No subtitle cues were found")
    if target_format == "ass":
        output = _to_ass(cues)
    else:
        blocks = []
        for index, (start, end, text) in enumerate(cues, 1):
            timing = f"{_format_time(start, '.' if target_format == 'vtt' else ',')} --> " \
                     f"{_format_time(end, '.' if target_format == 'vtt' else ',')}"
            blocks.append((f"{index}\n" if target_format == "srt" else "") + timing + "\n" + text)
        output = ("WEBVTT\n\n" if target_format == "vtt" else "") + "\n\n".join(blocks) + "\n"
    destination = OutputPolicy(directory=Path(directory) if directory else None).destination(source, target_format)
    return atomic_write(destination, lambda temporary: temporary.write_text(output, encoding="utf-8"))


def subtitle_to_text(source: str | Path, *, directory=None) -> Path:
    source = Path(source)
    cues = _read_cues(source)
    if not cues:
        raise ConversionError("No subtitle cues were found")
    lines = []
    for _, _, text in cues:
        clean = re.sub(r"<[^>]+>", "", text)
        clean = html.unescape(re.sub(r"\{[^}]*\}", "", clean)).replace(r"\N", "\n")
        clean = clean.strip()
        if clean and (not lines or lines[-1] != clean):
            lines.append(clean)
    destination = OutputPolicy(directory=Path(directory) if directory else None).destination(source, "txt")
    return atomic_write(destination, lambda temporary: temporary.write_text("\n".join(lines) + "\n", encoding="utf-8"))
