"""Subtitle handling for video files: finding side files, tagging languages, listing embedded tracks.

Pure helpers with no dependency on the conversion engine, so they can be tested in isolation.
The engine supplies the ffmpeg path and runs the commands.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

SUBTITLE_SUFFIXES = frozenset({".srt", ".ass", ".ssa", ".vtt"})
TEXT_CODECS = frozenset({"subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text"})

# (ISO 639-2 code written into the container, English name shown as the track title, accepted tags)
_LANGUAGES = (
    ("ara", "Arabic", ("ar", "arabic")),
    ("eng", "English", ("en", "english")),
    ("fre", "French", ("fr", "fra", "french")),
    ("spa", "Spanish", ("es", "spanish")),
    ("ger", "German", ("de", "deu", "german")),
    ("tur", "Turkish", ("tr", "turkish")),
    ("rus", "Russian", ("ru",)),
    ("chi", "Chinese", ("zh", "zho")),
    ("jpn", "Japanese", ("ja",)),
    ("por", "Portuguese", ("pt",)),
    ("ita", "Italian", ("it",)),
    ("hin", "Hindi", ("hi",)),
    ("per", "Persian", ("fa", "fas")),
    ("urd", "Urdu", ("ur",)),
    ("kor", "Korean", ("ko",)),
    ("ind", "Indonesian", ("id",)),
)
_TAG_TO_CODE = {tag: code for code, _name, tags in _LANGUAGES for tag in (code, *tags)}
LANGUAGE_NAMES = {code: name for code, name, _tags in _LANGUAGES}

_NAME_SEPARATORS = re.compile(r"[ _\-]")
_STREAM_LINE = re.compile(r"\s*Stream #0:\d+(?:\[\w+\])?(?:\((\w+)\))?: Subtitle: (\w+)")
_FILTER_SPECIALS = str.maketrans({":": "\\:", "'": "\\'"})
_ENCODINGS = ("utf-8-sig", "cp1256", "latin-1")


@dataclass
class Track:
    index: int
    codec: str
    lang: str = ""
    title: str = ""

    @property
    def is_text(self) -> bool:
        return self.codec in TEXT_CODECS

    def as_dict(self) -> dict:
        return {"index": self.index, "lang": self.lang, "codec": self.codec,
                "title": self.title, "text": self.is_text}


def sidecar_files(video) -> list[str]:
    """Subtitle files in the video's folder whose names start with the video's name."""
    video = Path(video)
    prefix = video.stem.lower()
    try:
        names = list(video.parent.iterdir())
    except OSError:
        return []
    return sorted(str(p) for p in names
                  if p.suffix.lower() in SUBTITLE_SUFFIXES and p.name.lower().startswith(prefix))


def filter_escape(path) -> str:
    """A path written so ffmpeg's filter parser keeps it in one piece (drive colons, quotes)."""
    return str(Path(path)).replace("\\", "/").translate(_FILTER_SPECIALS)


def decode_text(raw: bytes) -> str:
    """Decode subtitle bytes: UTF-8 (with or without BOM), then Windows Arabic, then Latin-1."""
    for encoding in _ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    return raw.decode("latin-1", "replace")


def guess_language(path, text: str) -> str | None:
    """A three-letter language code from the file name tags (movie.ar.srt), else from the script used."""
    pieces = [p for p in _NAME_SEPARATORS.sub(".", Path(path).stem.lower()).split(".")][1:]
    for piece in reversed(pieces):
        code = _TAG_TO_CODE.get(piece)
        if code:
            return code
    letters = [ch for ch in text[:4000] if ch.isalpha()]
    if letters:
        arabic = sum(1 for ch in letters if "\u0600" <= ch <= "\u06ff")
        if arabic * 2 > len(letters):
            return "ara"
    return None


def parse_tracks(ffmpeg_report: str) -> list[Track]:
    """Subtitle tracks listed in the text `ffmpeg -i file` prints to stderr."""
    tracks: list[Track] = []
    current: Track | None = None
    for line in ffmpeg_report.splitlines():
        found = _STREAM_LINE.match(line)
        if found:
            current = Track(index=len(tracks), codec=found.group(2).lower(), lang=found.group(1) or "")
            tracks.append(current)
            continue
        stripped = line.strip()
        if stripped.startswith("Stream #"):
            current = None
        elif current is not None and stripped.lower().startswith("title"):
            current.title = line.split(":", 1)[1].strip()
    return tracks


def count_tracks(ffmpeg_report: str) -> int:
    return ffmpeg_report.count(": Subtitle:")


def file_tag(track: Track) -> str:
    """The name part used when saving a track as .srt (language, else its title, else its number)."""
    base = track.lang if track.lang and track.lang != "und" else track.title
    return re.sub(r'[<>:"/\\|?*]', "", base)[:40] or str(track.index + 1)


def mux_options(position: int, existing: int, file: Path, text: str, first: bool) -> list[str]:
    """ffmpeg output options labelling subtitle track number `existing + position`."""
    slot = existing + position
    code = guess_language(file, text)
    codec = "ass" if file.suffix.lower() in (".ass", ".ssa") else "srt"
    options = [f"-c:s:{slot}", codec, f"-metadata:s:s:{slot}", f"title={LANGUAGE_NAMES.get(code, file.stem)}"]
    if code:
        options += [f"-metadata:s:s:{slot}", f"language={code}"]
    options += [f"-disposition:s:{slot}", "default" if first else "0"]
    return options
