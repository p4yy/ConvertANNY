"""
ConvertANNY conversion engine.

Everything here runs locally. No network calls.
Backends:
  - Pillow (+ pillow-heif)          images
  - ffmpeg (bundled by imageio-ffmpeg) video / audio
  - PyMuPDF                         PDF, EPUB, SVG, HTML/Markdown -> PDF
  - openpyxl                        spreadsheets
  - Microsoft Office (COM) or LibreOffice, if installed   DOCX/PPTX/XLS(X) -> PDF etc.
  - stdlib + py7zr                  archives (zip/7z/tar…), subtitles; RAR via 7-Zip/WinRAR/tar.exe
"""
from __future__ import annotations

import csv
import io
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import logging
logging.getLogger().setLevel(logging.WARNING)   # pdf2docx is chatty

# New ConvertANNY-owned operations are developed in this package first. The
# surrounding catalog remains compatible with the existing UI/job protocol.
from convertanny_core.documents import text_to_pdf as _owned_text_to_pdf
from convertanny_core.document_stats import document_stats as _owned_document_stats
from convertanny_core.images import (convert_image as _owned_convert_image,
                                    supported_formats as _owned_image_formats,
                                    transform_image as _owned_transform_image,
                                    compress_image as _owned_compress_image,
                                    crop_resize_image as _owned_crop_resize_image,
                                    resize_preset_image as _owned_resize_preset_image,
                                    watermark_image as _owned_watermark_image,
                                    enhance_image as _owned_enhance_image,
                                    resize_image as _owned_resize_image)
from convertanny_core.background import remove_background as _owned_remove_background
from convertanny_core.encoding_tools import repair_arabic_file as _owned_repair_arabic_file
from convertanny_core.documents import images_to_pdf as _owned_images_to_pdf
from convertanny_core.documents import merge_pdfs as _owned_merge_pdfs
from convertanny_core.documents import rotate_pdf as _owned_rotate_pdf
from convertanny_core.documents import extract_pdf_pages as _owned_extract_pdf_pages
from convertanny_core.documents import pdf_to_text as _owned_pdf_to_text
from convertanny_core.documents import split_pdf as _owned_split_pdf
from convertanny_core.documents import pdf_to_images as _owned_pdf_to_images
from convertanny_core.documents import grayscale_pdf as _owned_grayscale_pdf
from convertanny_core.documents import (compress_pdf as _owned_compress_pdf,
                                        protect_pdf as _owned_protect_pdf,
                                        unlock_pdf as _owned_unlock_pdf,
                                        extract_pdf_images as _owned_extract_pdf_images)
from convertanny_core.documents import number_pdf_pages as _owned_number_pdf_pages
from convertanny_core.documents import watermark_pdf as _owned_watermark_pdf
from convertanny_core.documents import arrange_pdf as _owned_arrange_pdf, sign_pdf as _owned_sign_pdf
from convertanny_core.documents import pdf_to_markdown as _owned_pdf_to_markdown, pdf_to_html as _owned_pdf_to_html
from convertanny_core.documents import pdf_to_docx as _owned_pdf_to_docx
from convertanny_core.documents import pdf_to_docx_pages as _owned_pdf_to_docx_pages
from convertanny_core.documents import pdf_to_xlsx as _owned_pdf_to_xlsx
from convertanny_core.documents import ebook_to_pdf as _owned_ebook_to_pdf, ebook_to_text as _owned_ebook_to_text
from convertanny_core.documents import text_to_html_file as _owned_text_to_html
from convertanny_core.documents import html_to_markdown_file as _owned_html_to_markdown
from convertanny_core.documents import text_to_docx as _owned_text_to_docx
from convertanny_core.documents import markdown_to_text_file as _owned_markdown_to_text
from convertanny_core.media import waveform_peaks as _owned_waveform_peaks, create_ringtone as _owned_create_ringtone
from convertanny_core.media import convert_audio as _owned_convert_audio, process_audio as _owned_process_audio
from convertanny_core.video import (convert_video as _owned_convert_video,
                                    process_video as _owned_process_video,
                                    compress_video_to_size as _owned_compress_video_to_size,
                                    social_crop_video as _owned_social_crop_video)
from convertanny_core.tables import (table_to_delimited as _owned_table_to_delimited,
                                     table_to_xlsx as _owned_table_to_xlsx,
                                     table_to_json as _owned_table_to_json,
                                     table_to_html as _owned_table_to_html,
                                     table_to_markdown as _owned_table_to_markdown)
from convertanny_core.subtitles import (convert_subtitle as _owned_convert_subtitle,
                                        subtitle_to_text as _owned_subtitle_to_text)
from convertanny_core.archives import (archive_format as _owned_archive_format,
                                       create_archive as _owned_create_archive,
                                       create_protected_archive as _owned_create_protected_archive,
                                       extract_archive as _owned_extract_archive,
                                       extract_archive_into as _owned_extract_archive_into,
                                       repack_archive as _owned_repack_archive,
                                       gzip_file as _owned_gzip_file,
                                       can_write_rar as _owned_can_write_rar)
from convertanny_core.fonts import convert_font as _owned_convert_font, install_font as _owned_install_font
from convertanny_core.scanner import detect_document,straighten,scan_image as _owned_scan_image
from convertanny_core.office import libreoffice_executable as soffice, office_available as _owned_office_available, convert_office as _owned_office_convert
from convertanny_core.model import ConversionError as _OwnedConversionError
from convertanny_core.paths import OutputPolicy as _OwnedOutputPolicy
from convertanny_core.processes import DesktopCancelToken as CancelToken
from convertanny_core.volumes import split_file as _owned_split_file, join_files as _owned_join_files, is_part_file as _owned_is_part_file
from convertanny_core.pdf_comics import pdf_to_cbz as _owned_pdf_to_cbz
from convertanny_core.html_render import html_to_pdf as _owned_html_to_pdf, HTML_DOCUMENT_CSS
from convertanny_core.sheet_render import spreadsheet_to_pdf as _owned_sheet_to_pdf
from convertanny_core.slide_render import slide_image_converter as _owned_slide_image_converter
from convertanny_core.windows_ocr import recognize_image_text as _owned_ocr

IS_WIN = sys.platform == "win32"
OUTPUT_DIR: str | None = None   # None = save next to the original
NO_WINDOW = 0x08000000 if IS_WIN else 0  # CREATE_NO_WINDOW
DETACHED = 0x00000008 if IS_WIN else 0   # DETACHED_PROCESS: no console at all (so a tool can't beep through one)
# Heavy tools (ffmpeg, whisper…) run below normal priority so a video playing in a float stays smooth.
LOW_PRIORITY = 0x00004000 if IS_WIN else 0  # BELOW_NORMAL_PRIORITY_CLASS

# ----------------------------------------------------------------------------
# Categories
# ----------------------------------------------------------------------------
EXT_CATEGORY = {
    # images
    **{e: "image" for e in "jpg jpeg png webp heic heif tif tiff avif bmp gif ico svg psd tga dds jp2 j2k jpx pcx ppm pgm pbm qoi icns".split()},
    # video
    **{e: "video" for e in "mp4 mov mkv webm avi wmv m4v flv mpg mpeg 3gp ts mts m2ts vob ogv mxf f4v asf".split()},
    # audio
    **{e: "audio" for e in "mp3 m4a m4r wav flac ogg oga opus aiff aif wma aac ac3 mka caf m4b amr au dts".split()},
    "pdf": "pdf",
    **{e: "document" for e in "docx doc rtf odt md markdown txt html htm".split()},
    **{e: "slides" for e in "pptx ppt odp key".split()},
    **{e: "spreadsheet" for e in "xlsx xlsm xls ods csv tsv".split()},
    **{e: "subtitle" for e in "srt vtt ass ssa".split()},
    **{e: "font" for e in "ttf otf woff woff2".split()},
    **{e: "ebook" for e in "epub mobi fb2 xps oxps".split()},
    **{e: "comic" for e in "cbz cbr cb7 cbt".split()},
    **{e: "archive" for e in "zip tar gz tgz bz2 tbz2 xz txz 7z rar iso cab".split()},
}

CATEGORY_LABEL = {
    "image": "Image", "video": "Video", "audio": "Audio", "pdf": "PDF",
    "document": "Document", "slides": "Slides", "spreadsheet": "Spreadsheet",
    "subtitle": "Subtitles", "font": "Font", "ebook": "E-book", "comic": "Comic book", "archive": "Archive",
    "folder": "Folder", "mixed": "Files", "other": "File",
}


# Archive names whose "extension" spans two dots, mapped to the short form the catalogue uses.
_COMPOUND_EXTENSIONS = {".tar.gz": "tgz", ".tar.bz2": "tbz2", ".tar.xz": "txz"}
_EXTENSION_ALIASES = {"tbz": "tbz2"}


def ext_of(p: str | Path) -> str:
    """Catalogue extension for a path: lower case, no dot, compound tar suffixes collapsed."""
    base = os.path.basename(os.fspath(p)).lower()
    for tail, short in _COMPOUND_EXTENSIONS.items():
        if base.endswith(tail):
            return short
    ext = os.path.splitext(base)[1].lstrip(".")
    return _EXTENSION_ALIASES.get(ext, ext)


def category_of(paths: list[str]) -> str:
    """The single category shared by every path, or "mixed" when they differ (or none are given)."""
    kinds = {"folder" if os.path.isdir(item) else EXT_CATEGORY.get(ext_of(item), "other")
             for item in paths}
    return next(iter(kinds)) if len(kinds) == 1 else "mixed"


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
class ConversionError(Exception):
    """A file could not be converted; the message is shown to the user."""


# ----------------------------------------------------------------------------
# Cancellation: each job runs with a CancelToken (thread-local). Cancel kills any
# external process of the job, loops call check_cancel(), and outputs are deleted.
# ----------------------------------------------------------------------------
import threading

_ctx = threading.local()


class Cancelled(Exception):
    """Raised inside a job when the user cancels it."""




def _token() -> CancelToken | None:
    """The cancellation token of the job running on this thread, if any."""
    return _ctx.__dict__.get("token")


def check_cancel():
    """Abort the current job (by raising Cancelled) if its token has been cancelled."""
    token = _token()
    if token is not None and token.cancelled:
        raise Cancelled()


class _OwnedCancelAdapter:
    """Pass the desktop job's cooperative cancellation into ConvertANNY core operations."""

    def check(self):
        check_cancel()

    def report(self, value):
        check_cancel()
        report_progress(value)


def _remember(path: Path, kind: str = "out") -> Path:
    """Register a path with the running job: outputs are tracked for cleanup, all kinds are announced."""
    token = _token()
    if token is None:
        return path
    if kind == "out":
        token.paths.append(path)
    announce = token.on_path
    if announce:
        try:
            announce(kind, str(path))
        except Exception:
            pass        # a vanished UI must never fail a conversion
    return path


def temp_dir() -> Path:
    """A private temp folder for the current job (reported so it can be removed if the job is killed)."""
    import tempfile
    return _remember(Path(tempfile.mkdtemp(prefix="convertanny-")), "tmp")


_TAR_SUFFIXES = (".tar.gz", ".tar.bz2", ".tar.xz")


def _split_name(name: str) -> tuple[str, str]:
    """Split a file name into (stem, suffix), keeping .tar.gz/.tar.bz2/.tar.xz together."""
    lowered = name.lower()
    for tail in _TAR_SUFFIXES:
        if lowered.endswith(tail):
            return name[:-len(tail)], name[-len(tail):]
    stem, suffix = os.path.splitext(name)
    return stem, suffix


def unique_path(path: Path) -> Path:
    """`path` if it is free, otherwise the first free "name (2).ext", "name (3).ext", ..."""
    if not path.exists():
        return _remember(path)
    stem, suffix = _split_name(path.name)
    for number in itertools.count(2):
        candidate = path.with_name(f"{stem} ({number}){suffix}")
        if not candidate.exists():
            return _remember(candidate)


def _target_dir(src: Path) -> Path:
    """Where outputs for `src` go: the chosen output folder when it exists, else beside the source."""
    chosen = OUTPUT_DIR
    if chosen and os.path.isdir(chosen):
        return Path(chosen)
    return src.parent


def out_for(src: str | Path, ext: str, tag: str = "") -> Path:
    """A free output path for converting `src` to `ext`, with an optional " tag" after the name."""
    src = Path(src)
    if src.name.lower().endswith(".tar.gz"):
        stem = src.name[:-len(".tar.gz")]
    else:
        stem = src.stem
    label = f" {tag}" if tag else ""
    return unique_path(_target_dir(src) / f"{stem}{label}.{ext}")


def out_dir_for(src: str | Path, tag: str) -> Path:
    """A free folder path named "<source name> <tag>" for operations that produce many files."""
    src = Path(src)
    return unique_path(_target_dir(src) / f"{src.stem} {tag}")


def _unit_interval(value: float) -> float:
    return min(1.0, max(0.0, value))


def report_progress(frac: float, token=None) -> None:
    """Publish job progress (0..1) to the UI; a batch is folded into one overall bar."""
    token = token if token is not None else _token()
    if token is None or not token.on_path:
        return
    done, total = getattr(token, "batch", (0, 1))
    overall = _unit_interval((done + _unit_interval(frac)) / max(1, total))
    try:
        token.on_path("progress", f"{overall:.4f}")
    except Exception:
        pass


def run(cmd, cwd=None, ok_codes=(0,), progress_total=0.0, span=(0.0,1.0), detached=False):
    from convertanny_core.processes import run_tool
    token=_token()
    return run_tool(cmd,cwd=cwd,accepted=ok_codes,duration=progress_total,span=span,detached=detached,
                    token=token,check=check_cancel,progress=lambda value:report_progress(value,token),
                    error_type=ConversionError)


_TIME_TEXT = re.compile(r"[\d:.]+")


def parse_time(t: str) -> str:
    """Validate a user-typed time ("90", "1:30", "00:01:30.5") and return it as ffmpeg expects."""
    text = str(t).strip()
    if _TIME_TEXT.fullmatch(text) is None:
        raise ConversionError(f"Invalid time: {text}")
    return text


# ----------------------------------------------------------------------------
# ffmpeg
# ----------------------------------------------------------------------------
_FFMPEG = None


def ffmpeg() -> str:
    """Path to an ffmpeg executable: the one on PATH, else the copy bundled by imageio-ffmpeg."""
    global _FFMPEG
    if _FFMPEG:
        return _FFMPEG
    found = shutil.which("ffmpeg")
    if not found:
        try:
            import imageio_ffmpeg
            found = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            found = None
    if not found:
        raise ConversionError("ffmpeg not found. Run: pip install imageio-ffmpeg")
    _FFMPEG = found
    return found


def cover_art(src) -> bytes | None:
    """The cover picture embedded in an audio file, as PNG bytes, or None if there is none."""
    command = [ffmpeg(), "-hide_banner", "-loglevel", "error", "-i", str(src), "-an",
               "-map", "0:v:0?", "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"]
    try:
        result = subprocess.run(command, capture_output=True, timeout=8,
                                stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
    except Exception:
        return None
    picture = result.stdout
    return picture if result.returncode == 0 and len(picture) > 100 else None


_DURATIONS = {}


def _secs(t) -> float:
    """Seconds in a "ss", "mm:ss" or "hh:mm:ss.fff" string; 0.0 when it cannot be read."""
    total = 0.0
    try:
        for part in str(t).strip().split(":"):
            total = total * 60 + float(part)
    except ValueError:
        return 0.0
    return total


_DURATION_LINE = re.compile(rb"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def media_duration(src) -> float:
    """Length in seconds of a video/audio file (0 if it cannot be determined); cached per path."""
    key = str(src)
    if key in _DURATIONS:
        return _DURATIONS[key]
    length = 0.0
    try:
        probe = subprocess.run([ffmpeg(), "-hide_banner", "-i", key], capture_output=True, timeout=20,
                               stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
        match = _DURATION_LINE.search(probe.stderr)
        if match:
            hours, minutes, seconds = match.groups()
            length = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except Exception:
        length = 0.0
    _DURATIONS[key] = length
    return length


def _flag_value(argv, flag: str) -> str | None:
    """The argument following `flag` in an ffmpeg argument list, or None if absent/dangling."""
    items = [str(x) for x in argv]
    try:
        return items[items.index(flag) + 1]
    except (ValueError, IndexError):
        return None


def _expected_seconds(src, args, pre) -> float:
    """Estimated output length in seconds, used to turn ffmpeg's progress into a percentage."""
    limit = _flag_value(args, "-t")
    if limit is not None:
        return _secs(limit)
    total = media_duration(src) if EXT_CATEGORY.get(ext_of(src)) in ("video", "audio") else 0.0
    start = _flag_value(pre, "-ss")
    if start is not None:
        total -= _secs(start)
    stop = _flag_value(args, "-to")
    if stop is not None:
        stop_at = _secs(stop)
        total = min(total, stop_at) if total > 0 else stop_at
    if any("setpts=0.5" in str(x) for x in args):
        total /= 2
    return max(0.0, total)


def ff(src, out, *args, pre: tuple = (), span: tuple = (0.0, 1.0)) -> Path:
    """Run ffmpeg once (`pre` options before the input, `args` after it), reporting progress when possible."""
    expected = _expected_seconds(src, args, pre) if _token() is not None else 0.0
    track_progress = expected > 1
    command = [ffmpeg(), "-hide_banner", "-loglevel", "error", "-y"]
    if track_progress:
        command += ["-progress", "pipe:1", "-nostats"]
    command += [*pre, "-i", str(src), *args, str(out)]
    run(command, progress_total=expected if track_progress else 0.0, span=span)
    return Path(out)


VIDEO_ARGS = {
    "mp4": ["-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"],
    "mov": ["-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k"],
    "mkv": ["-c:v", "libx264", "-crf", "20", "-c:a", "aac", "-b:a", "192k"],
    "mkv_hevc": ["-c:v", "libx265", "-preset", "medium", "-crf", "24", "-pix_fmt", "yuv420p", "-c:a", "aac",
                 "-b:a", "192k", "-x265-params", "log-level=error"],
    "webm": ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "33", "-deadline", "good", "-cpu-used", "5",
             "-row-mt", "1", "-c:a", "libopus", "-b:a", "128k"],
    "avi": ["-c:v", "mpeg4", "-q:v", "4", "-c:a", "libmp3lame", "-q:a", "3"],
    "wmv": ["-c:v", "wmv2", "-q:v", "4", "-c:a", "wmav2", "-b:a", "192k"],
}

AUDIO_ARGS = {
    "mp3": ["-vn", "-c:a", "libmp3lame", "-q:a", "2"],
    "m4a": ["-vn", "-c:a", "aac", "-b:a", "192k"],
    "wav": ["-vn", "-c:a", "pcm_s16le"],
    "flac": ["-vn", "-c:a", "flac"],
    "ogg": ["-vn", "-c:a", "libvorbis", "-q:a", "5"],
    "opus": ["-vn", "-c:a", "libopus", "-b:a", "128k"],
    "aiff": ["-vn", "-c:a", "pcm_s16be"],
    "wma": ["-vn", "-c:a", "wmav2", "-b:a", "192k"],
    "ac3": ["-vn", "-c:a", "ac3", "-b:a", "448k"],
}


def video_to(fmt):
    def f(src, p):
        token = _token()
        return _owned_convert_video(
            src,
            fmt,
            ffmpeg=ffmpeg(),
            policy=_OwnedOutputPolicy(directory=_target_dir(Path(src)), suffix=" hevc" if fmt == "mkv_hevc" else ""),
            token=_OwnedCancelAdapter() if token is not None else None,
        )
    return f


def audio_to(fmt):
    def f(src, p):
        token = _token()
        return _owned_convert_audio(
            src,
            fmt,
            ffmpeg=ffmpeg(),
            policy=_OwnedOutputPolicy(directory=_target_dir(Path(src))),
            token=_OwnedCancelAdapter() if token is not None else None,
        )
    return f


def video_to_gif(src, p):
    vf = "fps=12,scale='min(640,iw)':-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4"
    token = _token()
    return _owned_process_video(src, "gif", ["-vf", vf, "-loop", "0"], ffmpeg=ffmpeg(), suffix="",
                                policy=_OwnedOutputPolicy(directory=_target_dir(Path(src))),
                                token=_OwnedCancelAdapter() if token is not None else None)


# ---- 1.2 video & audio tools
TARGET_SIZES = ["8 MB", "10 MB", "25 MB", "50 MB", "100 MB", "500 MB"]


def video_to_size(src, p):
    target_mb = float(str(p.get("Target size", "25 MB")).split()[0])
    token = _token()
    return _owned_compress_video_to_size(
        src, target_mb, ffmpeg=ffmpeg(),
        policy=_OwnedOutputPolicy(directory=_target_dir(Path(src)), suffix=f" {int(target_mb)}MB"),
        token=_OwnedCancelAdapter() if token is not None else None,
    )


SOCIAL_SHAPES = ["9:16 — Reel · Story · TikTok · Shorts", "1:1 — Square post", "4:5 — Instagram & Facebook post",
                 "2:3 — Pinterest pin", "16:9 — YouTube · widescreen"]


_YUNET = None


def detect_faces(rgb, score_thr=0.6, nms_thr=0.3) -> list[tuple[float, float, float, float, float]]:
    """Return detected face bounds through ConvertANNY's detector adapter."""
    global _YUNET
    from convertanny_core import faces
    if _YUNET is None:
        _YUNET = faces.open_session(_asset("models", "face_detection_yunet_2023mar.onnx"))
    return faces.detect(_YUNET, rgb, score_thr, nms_thr)


def _face_center_x(src, samples=6) -> float | None:
    """Estimate the horizontal subject position from evenly spaced video frames."""
    try:
        import statistics
        Image, _ = _pil()
        length = media_duration(src)
        folder = temp_dir()
        seen = []
        for n in range(samples):
            check_cancel()
            frame_png = folder / f"f{n}.png"
            time_at = length * (n + 0.5) / samples
            run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{time_at:.2f}",
                 "-i", str(src), "-frames:v", "1", "-vf", "scale=640:-2", str(frame_png)])
            if not frame_png.exists():
                continue
            with Image.open(frame_png) as frame:
                frame.load()
                seen.extend((x + width / 2) / frame.width for x, _y, width, _height, _score in detect_faces(frame))
        return float(statistics.median(seen)) if seen else None
    except Exception:
        return None


def video_social_crop(src, p):
    shape = p.get("Shape", SOCIAL_SHAPES[0]).split()[0]          # "9:16 — Reel …" -> "9:16"
    try:
        cx = float(p["Center"])                 # where you placed the box in the preview
    except (KeyError, TypeError, ValueError):
        cx = _face_center_x(src)
    token = _token()
    return _owned_social_crop_video(
        src, shape, cx, ffmpeg=ffmpeg(),
        policy=_OwnedOutputPolicy(directory=_target_dir(Path(src)), suffix=f" {shape.replace(':', 'x')}"),
        token=_OwnedCancelAdapter() if token is not None else None,
    )


def preview_frame(src, out_png) -> bool:
    """One frame from the middle of a video, 640 px wide, for the crop preview."""
    from convertanny_core.video_presets import grab_frame
    return grab_frame(ffmpeg(), src, out_png, (media_duration(src) or 0.0) * 0.4,
                      creationflags=NO_WINDOW)


RINGTONE_FORMATS = ["iPhone (M4R)", "Android (MP3)"]


RINGTONE_MAX = 40.0          # iPhone won't take a ringtone longer than 40 s


def ringtone(src,params):
    clip=params.get("Clip")
    if not clip:
        start=_secs(parse_time(params.get("Start","0:00")));clip=f"{start}-{start+30}"
    return _owned_create_ringtone(src,clip,params.get("Format",RINGTONE_FORMATS[0]),ffmpeg=ffmpeg(),
        policy=_OwnedOutputPolicy(directory=_target_dir(Path(src)),suffix=" ringtone"),token=_OwnedCancelAdapter() if _token() is not None else None)


def waveform(src,bins=1200):
    return _owned_waveform_peaks(src,ffmpeg=ffmpeg(),bins=bins,token=_OwnedCancelAdapter() if _token() is not None else None)


from convertanny_core import subtitle_tracks as _tracks
_subs_cache: dict = {}
_BURN_STYLE = "FontName=Segoe UI,FontSize=22,Outline=2,Shadow=0,MarginV=28"

def _side_subtitles(video) -> list[str]:
    return _tracks.sidecar_files(video)



def _ff_filter_path(path) -> str:
    """Quote a file path for an ffmpeg filter argument (Windows drive colons and quotes)."""
    return _tracks.filter_escape(path)


def _ffmpeg_report(video, seconds: int) -> str:
    """What `ffmpeg -i` prints about a file (it exits non-zero, the stream list is on stderr)."""
    done = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(video)], capture_output=True,
                          stdin=subprocess.DEVNULL, creationflags=NO_WINDOW, timeout=seconds)
    return done.stderr.decode("utf-8", "ignore")


def _subtitle_inputs(paths) -> tuple[Path, list[str]]:
    """The video among `paths`, and the subtitle files to use: those given, else the ones beside it."""
    video = next(x for x in paths if EXT_CATEGORY.get(ext_of(x)) == "video")
    chosen = [x for x in paths if EXT_CATEGORY.get(ext_of(x)) == "subtitle"] or _side_subtitles(video)
    if not chosen:
        raise ConversionError("No subtitle file found")
    return video, chosen


def burn_subtitles(paths, p):
    """Burn subtitles into the picture: the video plus a subtitle file dragged with it, or one next to it."""
    video, chosen = _subtitle_inputs(paths)
    source = Path(chosen[0])
    # libass wants UTF-8 and a plain path, so hand it a re-encoded copy in a private folder
    staged = temp_dir() / f"subs{source.suffix.lower()}"
    staged.write_text(_tracks.decode_text(source.read_bytes()), encoding="utf-8")
    graph = f"subtitles='{_ff_filter_path(staged)}'"
    if source.suffix.lower() in (".srt", ".vtt"):
        graph += f":force_style='{_BURN_STYLE}'"
    return ff(video, out_for(video, "mp4", "subtitled"), "-vf", graph,
              "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p",
              "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart")



_SUB_LANGS = {"ar": "ara", "ara": "ara", "arabic": "ara", "en": "eng", "eng": "eng", "english": "eng",
              "fr": "fre", "fre": "fre", "fra": "fre", "french": "fre", "es": "spa", "spa": "spa", "spanish": "spa",
              "de": "ger", "ger": "ger", "deu": "ger", "german": "ger", "tr": "tur", "tur": "tur", "turkish": "tur",
              "ru": "rus", "rus": "rus", "zh": "chi", "chi": "chi", "zho": "chi", "ja": "jpn", "jpn": "jpn",
              "pt": "por", "por": "por", "it": "ita", "ita": "ita", "hi": "hin", "hin": "hin", "fa": "per",
              "per": "per", "fas": "per", "ur": "urd", "urd": "urd", "ko": "kor", "kor": "kor", "id": "ind", "ind": "ind"}


_LANG_NAMES = {"ara": "Arabic", "eng": "English", "fre": "French", "spa": "Spanish", "ger": "German", "tur": "Turkish",
               "rus": "Russian", "chi": "Chinese", "jpn": "Japanese", "por": "Portuguese", "ita": "Italian",
               "hin": "Hindi", "per": "Persian", "urd": "Urdu", "kor": "Korean", "ind": "Indonesian"}


def _sub_language(path, text) -> str | None:
    return _tracks.guess_language(path, text)



def mux_subtitles(paths, p):
    """Add subtitle files to the video as tracks you can switch on and off (MKV, nothing re-encoded):
    the subtitle files dragged with it, or every matching one next to it (movie.ar.srt, movie.en.srt...)."""
    video, chosen = _subtitle_inputs(paths)
    workdir = temp_dir()
    already = _tracks.count_tracks(_ffmpeg_report(video, 60))
    inputs: list[str] = []
    maps = ["-map", "0"]
    labels: list[str] = []
    for position, name in enumerate(chosen):
        source = Path(name)
        text = _tracks.decode_text(source.read_bytes())      # MKV text subtitles are UTF-8
        staged = workdir / f"sub{position}{source.suffix.lower()}"
        staged.write_text(text, encoding="utf-8")
        inputs += ["-sub_charenc", "UTF-8", "-i", str(staged)]
        maps += ["-map", f"{position + 1}:s:0"]
        labels += _tracks.mux_options(position, already, source, text, first=position == 0)
    # the tracks the video already had stop being the default, so the new first one shows
    demote = [opt for n in range(already) for opt in (f"-disposition:s:{n}", "0")]
    out = out_for(video, "mkv", "subtitles")
    run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(video), *inputs, *maps,
         "-c:v", "copy", "-c:a", "copy", "-c:s", "copy", *demote, *labels, str(out)])
    return out



_TEXT_SUB_CODECS = ("subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text")
_subs_cache: dict = {}


def subtitle_streams(video) -> list[dict]:
    """Subtitle tracks inside a video: [{"index", "codec", "lang", "title", "text"}] (text=False for picture subtitles)."""
    try:
        key = (str(video), os.path.getmtime(video))
    except OSError:
        return []
    if key not in _subs_cache:
        try:
            _subs_cache[key] = [t.as_dict() for t in _tracks.parse_tracks(_ffmpeg_report(video, 30))]
        except Exception:
            _subs_cache[key] = []
    return _subs_cache[key]



def extract_subtitles(src, p):
    """Save every text subtitle track inside the video as an .srt next to it: movie.ara.srt, movie.eng.srt..."""
    everything = subtitle_streams(src)
    wanted = [t for t in everything if t["text"]]
    if not wanted:
        raise ConversionError("This video's subtitles are pictures, not text, so they can't be saved as SRT"
                              if everything else "No subtitles inside this video")
    video = Path(src)
    taken: set[str] = set()
    saved = []
    for info in wanted:
        track = _tracks.Track(index=info["index"], codec=info["codec"], lang=info["lang"], title=info["title"])
        label = _tracks.file_tag(track)
        while label in taken:
            label += f" {track.index + 1}"
        taken.add(label)
        target = unique_path(_target_dir(video) / f"{video.stem}.{label}.srt")   # video's name, so players load it
        run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
             "-map", f"0:s:{track.index}", "-c:s", "srt", str(target)])
        saved.append(target)
    return saved



# ---- links (Play copied link in Float)
MEDIA_LINK_EXT = (".mp4", ".m4v", ".mov", ".webm", ".mkv", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav",
                  ".flac", ".m3u8", ".mpd")


_WEB_SCHEMES = ("http://", "https://")


def is_link(text) -> bool:
    """True for a single web address (no spaces or line breaks) that can be handed to the link resolver."""
    candidate = (text or "").strip()
    if any(ch in candidate for ch in " \n"):
        return False
    return candidate.lower().startswith(_WEB_SCHEMES)


# YouTube hands different streams to different "players"; asking several at once gets a playable choice in one go
_YT_CLIENTS = "youtube:player_client=default,web_safari,android_vr,tv,mweb"
LINK_QUALITIES = ["1080p", "720p", "480p", "360p"]


def _link_log(msg):
    try:
        import winsys
        winsys.log(msg)
    except Exception:
        pass


# YouTube live: some players' streams get "403 Forbidden" on segments after a few seconds (they need a token
# ConvertANNY doesn't have). Players that did that are remembered for the session and skipped next time.
LIVE_BAD_CLIENTS = set()
# mweb's live playlist keeps working (android_vr's segments are refused after ~30 s); mweb needs the JS runtime
LIVE_CLIENT_ORDER = ["mweb", "tv", "web_safari", "android_vr"]
_LIVE_CLIENT_RANK = {"MWEB": 0, "TVHTML5": 1, "TVHTML5_SIMPLY_EMBEDDED_PLAYER": 1, "IOS": 3, "ANDROID_VR": 4, "ANDROID": 4,
                     "WEB_SAFARI": 2, "WEB": 5}


def yt_client(url) -> str:
    from convertanny_core.playback_choice import player_from_url
    return player_from_url(url)



def _pick_formats(info, max_h=1080, live=False) -> dict:
    """Translate extractor records into the playback descriptor used by Float."""
    from convertanny_core.playback_choice import choose_playback_format
    return choose_playback_format(info, max_height=max_h, is_live=live,
                                  client_for_url=yt_client, unavailable_live_clients=LIVE_BAD_CLIENTS,
                                  live_client_rank=_LIVE_CLIENT_RANK)


_PLAYER_HEADERS = ("user-agent", "referer", "origin", "cookie", "accept-language")
_ALT_HEADERS = ("user-agent", "referer", "origin")

def _live_player_infos(base_cmd, url) -> dict:
    """Ask each YouTube player for a live stream on its own, all at once. Players YouTube is known to refuse are
    skipped. {player: info} for those that answered, so the caller knows which player each stream came from."""
    running = {}
    for player in LIVE_CLIENT_ORDER:
        if player in LIVE_BAD_CLIENTS:
            continue
        running[player] = subprocess.Popen(base_cmd + ["--extractor-args", f"youtube:player_client={player}", url],
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
    answers = {}
    for player, proc in running.items():
        try:
            out, err = proc.communicate(timeout=60)
            if proc.returncode == 0:
                answers[player] = json.loads(out.decode("utf-8", "replace") or "{}")   # bad JSON lands in the except below
            else:
                tail = [ln for ln in err.decode("utf-8", "replace").splitlines() if ln.strip()][-1:]
                _link_log(f"live player {player}: {(tail or ['failed'])[0][:200]}")
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    return answers

def _parse_info(raw: bytes) -> dict:
    try:
        return json.loads(raw.decode("utf-8", "replace") or "{}")
    except ValueError:
        return {}

def _only_headers(headers, allowed) -> dict:
    return {name: value for name, value in (headers or {}).items() if name.lower() in allowed}

def _explain_failure(stderr_lines) -> str:
    errors = [ln for ln in stderr_lines if ln.startswith("ERROR")] or stderr_lines
    return (errors[-1] if errors else "Couldn't open this link").replace("ERROR: ", "")

def _live_alternatives(per_player: dict, max_h: int):
    """(best choice, the others) among per-player live results: players not marked bad come first."""
    options = []
    for player in LIVE_CLIENT_ORDER:
        picked = _pick_formats(per_player[player], max_h, True) if per_player.get(player) else {}
        if picked.get("url"):
            options.append(dict(picked, client=player))
    if not options:
        return None, []
    usable = [o for o in options if o["client"] not in LIVE_BAD_CLIENTS] or options
    best = usable[0]
    return best, [o for o in options if o is not best]

def resolve_link(url, quality=None, _updated=False) -> dict:
    """Turn a page link into something the float can play: {"url", "title", "page", "live"?, "audio"?, "headers", ...}.
    Direct media links play as they are; other sites go through yt-dlp (QuickJS solves YouTube's player
    challenge). One call, several YouTube players asked at once."""
    import time
    from urllib.parse import urlparse, unquote
    parsed = urlparse(url)
    path = unquote(parsed.path).lower()
    if path.endswith(MEDIA_LINK_EXT):
        return {"url": url, "title": Path(path).name or url, "page": url}
    if not model_ready("yt-dlp"):
        raise ConversionError("The yt-dlp tool isn't downloaded yet")
    max_h = int(str(quality or "1080p").rstrip("p") or 1080)
    exe = str(model_path("yt-dlp"))
    js_runtime = _asset("js", "qjs.exe")
    cmd = [exe, "-J", "--no-playlist", "--ignore-no-formats-error", "--extractor-args", _YT_CLIENTS]
    if js_runtime.exists():
        cmd += ["--js-runtimes", f"quickjs:{js_runtime}"]
    started = time.monotonic()
    on_youtube = (parsed.hostname or "").lower().endswith(("youtube.com", "youtu.be"))

    first = subprocess.run(cmd + [url], capture_output=True, timeout=90, stdin=subprocess.DEVNULL,
                           creationflags=NO_WINDOW)
    stderr_lines = first.stderr.decode("utf-8", "replace").strip().splitlines()
    info = _parse_info(first.stdout) if first.returncode == 0 else {}
    live = bool(info.get("is_live") or info.get("live_status") == "is_live")

    per_player = {}
    if on_youtube and live:
        plain = [c for c in cmd if c not in ("--extractor-args", _YT_CLIENTS)]
        per_player = _live_player_infos(plain, url)

    choice = _pick_formats(info, max_h, live) if info else {}
    spare = []
    if live and per_player:
        best, others = _live_alternatives(per_player, max_h)
        if best:
            choice, spare = best, others

    if not choice.get("url"):
        reason = _explain_failure(stderr_lines)
        warnings = " | ".join(ln for ln in stderr_lines if "WARNING" in ln)[:600]
        _link_log(f"yt-dlp: {reason} | {warnings}")
        if not _updated:                                # sites change: update yt-dlp once and retry
            update = subprocess.run([exe, "-U"], capture_output=True, timeout=120, stdin=subprocess.DEVNULL,
                                    creationflags=NO_WINDOW)
            _link_log("yt-dlp -U: " + update.stdout.decode("utf-8", "replace").strip().replace("\n", " | ")[-300:])
            return resolve_link(url, quality, _updated=True)
        raise ConversionError(reason if first.returncode else "Requested format is not available")

    result = dict(choice, title=info.get("title") or url, page=info.get("webpage_url") or url)
    result["headers"] = _only_headers(result.get("headers"), _PLAYER_HEADERS)
    result["client"] = result.get("client") or yt_client(result.get("url"))
    if live:
        result["live"] = True
        result["alts"] = [{"url": o["url"], "headers": _only_headers(o.get("headers"), _ALT_HEADERS),
                           "height": o.get("height"), "client": o["client"]} for o in spare]
    note = f"link opened in {time.monotonic() - started:.1f}s: {result.get('height')}p"
    if live:
        note += f" live via {result['client'] or '?'}"
    if result.get("audio"):
        note += " (picture + sound apart)"
    _link_log(note)
    return result



TRANSCRIBE_MODES = ["Detect language", "Arabic", "English", "Translate to English"]


def transcribe(src, p):
    from convertanny_core.speech import transcribe_audio
    if not model_ready('whisper-small'):
        raise ConversionError('The speech model is not downloaded yet')
    return transcribe_audio(src,p.get('Language','Detect language'),ffmpeg=ffmpeg(),
                            recognizer=_asset('whisper','whisper-cli.exe' if IS_WIN else 'whisper-cli'),
                            model=model_path('whisper-small'),directory=_target_dir(Path(src)),
                            token=_token(),check=check_cancel,progress=report_progress)


def video_gif_clip(src, p):
    """Make GIF… for videos: the part between Start and End, 12 fps, up to 640 px wide, good colours."""
    def secs(t):
        from convertanny_core.video_presets import clock_to_seconds
        return clock_to_seconds(parse_time(t))
    start, end = secs(p.get("Start", "0")), secs(p.get("End", "5"))
    if end <= start:
        raise ConversionError("End must be after Start")
    token = _token()
    vf = "fps=12,scale='min(640,iw)':-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4"
    return _owned_process_video(src, "gif", ["-t", f"{end - start:.3f}", "-vf", vf, "-loop", "0"],
                                ffmpeg=ffmpeg(), suffix=" clip",
                                policy=_OwnedOutputPolicy(directory=_target_dir(Path(src)), suffix=" clip"),
                                before_input=["-ss", f"{start:.3f}"],
                                token=_OwnedCancelAdapter() if token is not None else None)


def video_to_hevc(src, p):
    """H.265 in MP4: about half the size of H.264 at the same quality (plays on Windows 10/11, phones)."""
    from convertanny_core.video_presets import HEVC_MP4, encoder_args
    return ff(src, out_for(src, "mp4", "hevc"), *encoder_args(HEVC_MP4))


def video_compress(src, p):
    target = p.get("Target size", "Automatic")
    if target and target != "Automatic":
        return video_to_size(src, {"Target size": target})
    from convertanny_core.video_presets import SMALL_MP4, encoder_args
    return ff(src, out_for(src, "mp4", "compressed"), *encoder_args(SMALL_MP4))


def video_scale(h):
    def f(src, p):
        token = _token()
        return _owned_process_video(src, "mp4", ["-vf", f"scale=-2:'min({h},ih)'", "-c:v", "libx264",
                                  "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k"],
                                  ffmpeg=ffmpeg(), suffix=f" {h}p",
                                  policy=_OwnedOutputPolicy(directory=_target_dir(Path(src)), suffix=f" {h}p"),
                                  token=_OwnedCancelAdapter() if token is not None else None)
    return f


def video_mute(src, p):
    token = _token()
    return _owned_process_video(src, ext_of(src), ["-c:v", "copy", "-an"], ffmpeg=ffmpeg(), suffix=" muted",
                                policy=_OwnedOutputPolicy(directory=_target_dir(Path(src)), suffix=" muted"),
                                token=_OwnedCancelAdapter() if token is not None else None)


def media_trim(src, p):
    start, end = parse_time(p["Start"]), parse_time(p["End"])
    e = _norm(ext_of(src))
    if EXT_CATEGORY.get(ext_of(src)) == "video":
        token = _token()
        ext = e if e in VIDEO_ARGS else "mp4"
        args = VIDEO_ARGS[ext]
        duration = _secs(end) - _secs(start)
        if duration <= 0:
            raise ConversionError("End must be after Start")
        return _owned_process_video(
            src, ext, ["-t", f"{duration:.3f}", *args], ffmpeg=ffmpeg(), suffix=" trimmed",
            policy=_OwnedOutputPolicy(directory=_target_dir(Path(src)), suffix=" trimmed"),
            before_input=["-ss", start], token=_OwnedCancelAdapter() if token is not None else None,
        )
    else:
        ext = e if e in AUDIO_ARGS else "mp3"
        duration = _secs(end) - _secs(start)
        if duration <= 0:
            raise ConversionError("End must be after Start")
        profile = [arg for arg in AUDIO_ARGS[ext] if arg not in ("-vn", "-c:a", AUDIO_ARGS[ext][AUDIO_ARGS[ext].index("-c:a") + 1])]
        token = _token()
        return _owned_process_audio(
            src, ext, ["-t", f"{duration:.3f}", *profile], ffmpeg=ffmpeg(), suffix=" trimmed",
            policy=_OwnedOutputPolicy(directory=_target_dir(Path(src)), suffix=" trimmed"),
            before_input=["-ss", start], token=_OwnedCancelAdapter() if token is not None else None,
        )
    return ff(src, out_for(src, "mp3", "trimmed"), "-ss", start, "-to", end, *AUDIO_ARGS["mp3"])


def video_rotate(src, p):
    token = _token()
    return _owned_process_video(src, "mp4", ["-vf", "transpose=1", "-c:v", "libx264", "-crf", "20",
                                "-pix_fmt", "yuv420p", "-c:a", "copy"], ffmpeg=ffmpeg(), suffix=" rotated",
                                policy=_OwnedOutputPolicy(directory=_target_dir(Path(src)), suffix=" rotated"),
                                token=_OwnedCancelAdapter() if token is not None else None)


def video_snapshot(src, p):
    token = _token()
    return _owned_process_video(
        src, "png", ["-frames:v", "1"], ffmpeg=ffmpeg(), suffix=" frame",
        policy=_OwnedOutputPolicy(directory=_target_dir(Path(src)), suffix=" frame"),
        before_input=["-ss", parse_time(p["At time"])],
        token=_OwnedCancelAdapter() if token is not None else None,
    )


def has_audio(src) -> bool:
    """Whether the file has an audio stream; assumed True when it cannot be probed."""
    try:
        probe = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(src)], capture_output=True, timeout=20,
                               stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
    except Exception:
        return True
    return b"Audio:" in probe.stderr


def video_speed2x(src, p):
    out = out_for(src, "mp4", "2x")
    if not has_audio(src):                         # silent videos: speed up the picture only
        arguments = ["-vf", "setpts=0.5*PTS", "-an", "-c:v", "libx264", "-crf", "22", "-pix_fmt", "yuv420p"]
    else:
        arguments = ["-filter_complex", "[0:v]setpts=0.5*PTS[v];[0:a:0]atempo=2.0[a]",
                     "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "22", "-pix_fmt", "yuv420p",
                     "-c:a", "aac", "-b:a", "160k"]
    token = _token()
    return _owned_process_video(src, "mp4", arguments, ffmpeg=ffmpeg(), suffix=" 2x",
                                policy=_OwnedOutputPolicy(directory=_target_dir(Path(src)), suffix=" 2x"),
                                token=_OwnedCancelAdapter() if token is not None else None)


def audio_compress(src, p):
    token = _token()
    return _owned_process_audio(src, "mp3", ["-b:a", "96k"], ffmpeg=ffmpeg(), suffix=" compressed",
                                policy=_OwnedOutputPolicy(directory=_target_dir(Path(src)), suffix=" compressed"),
                                token=_OwnedCancelAdapter() if token is not None else None)


def audio_normalize(src, p):
    e = ext_of(src)
    ext = e if e in AUDIO_ARGS else "mp3"
    profile = [arg for arg in AUDIO_ARGS[ext] if arg not in ("-vn", "-c:a", AUDIO_ARGS[ext][AUDIO_ARGS[ext].index("-c:a") + 1])]
    token = _token()
    return _owned_process_audio(src, ext, ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11", *profile],
                                ffmpeg=ffmpeg(), suffix=" normalized",
                                policy=_OwnedOutputPolicy(directory=_target_dir(Path(src)), suffix=" normalized"),
                                token=_OwnedCancelAdapter() if token is not None else None)


def audio_mono(src, p):
    e = ext_of(src)
    ext = e if e in AUDIO_ARGS else "mp3"
    profile = [arg for arg in AUDIO_ARGS[ext] if arg not in ("-vn", "-c:a", AUDIO_ARGS[ext][AUDIO_ARGS[ext].index("-c:a") + 1])]
    token = _token()
    return _owned_process_audio(src, ext, ["-ac", "1", *profile], ffmpeg=ffmpeg(), suffix=" mono",
                                policy=_OwnedOutputPolicy(directory=_target_dir(Path(src)), suffix=" mono"),
                                token=_OwnedCancelAdapter() if token is not None else None)


def audio_fade(src, p):
    e = ext_of(src)
    ext = e if e in AUDIO_ARGS else "mp3"
    profile = [arg for arg in AUDIO_ARGS[ext] if arg not in ("-vn", "-c:a", AUDIO_ARGS[ext][AUDIO_ARGS[ext].index("-c:a") + 1])]
    token = _token()
    return _owned_process_audio(src, ext, ["-af", "afade=t=in:d=2,areverse,afade=t=in:d=2,areverse", *profile],
                                ffmpeg=ffmpeg(), suffix=" faded",
                                policy=_OwnedOutputPolicy(directory=_target_dir(Path(src)), suffix=" faded"),
                                token=_OwnedCancelAdapter() if token is not None else None)


def media_merge(paths, p):
    """Concatenate media files (re-encodes for safety)."""
    from convertanny_core import merge_graph
    first = Path(paths[0])
    with_video = EXT_CATEGORY.get(ext_of(first)) == "video"
    ext = "mp4" if with_video else ext_of(first)
    out = out_for(first, ext, "merged")
    encode = (merge_graph.VIDEO_ENCODE if with_video
              else merge_graph.audio_encode(AUDIO_ARGS.get(ext, AUDIO_ARGS["mp3"])[1:]))
    run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", *merge_graph.input_args(paths),
         "-filter_complex", merge_graph.concat_graph(len(paths), with_video), *encode, str(out)])
    return out



from convertanny_core import imagekit as _imagekit
from convertanny_core import pdf_handles as _pdf_handles

# ----------------------------------------------------------------------------
# Images
# ----------------------------------------------------------------------------
def _pil():
    """Pillow's Image and ImageOps, with HEIF/HEIC reading enabled when pillow-heif is present."""
    from PIL import Image, ImageOps
    _imagekit.enable_heif()
    return Image, ImageOps



def open_image(src):
    _pil()
    return _imagekit.load(src, ext_of(src) == "svg")



def _flatten(img, bg=(255, 255, 255)):
    """An opaque RGB copy; transparent areas are filled with `bg`."""
    return _imagekit.flatten(img, bg)



SAVE_KW = {
    "jpg": dict(format="JPEG", quality=92, optimize=True),
    "png": dict(format="PNG", optimize=True),
    "webp": dict(format="WEBP", quality=90, method=6),
    "tiff": dict(format="TIFF", compression="tiff_lzw"),
    "bmp": dict(format="BMP"),
    "gif": dict(format="GIF"),
    "avif": dict(format="AVIF", quality=75),
    "heic": dict(format="HEIF", quality=85),
    "ico": dict(format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]),
    "pdf": dict(format="PDF", resolution=150),
    "tga": dict(format="TGA", compression="tga_rle"),
    "jp2": dict(format="JPEG2000", quality_mode="dB", quality_layers=[38]),
    "icns": dict(format="ICNS"),
}


def save_image(img, out: Path, fmt: str, **override):
    options = {**SAVE_KW[fmt], **override}
    _imagekit.prepare_for_format(img, fmt).save(str(out), **options)
    return out



def image_to(fmt):
    def f(src, p):
        # Pillow-backed formats move to the new engine only when its codec is
        # present and the input is a raster format it can read directly.
        source = Path(src)
        if (fmt in _owned_image_formats() and ext_of(source) != "svg"
                and (fmt not in ("heic", "avif") or _pil()[0].SAVE.get("HEIF" if fmt == "heic" else "AVIF"))):
            token = _token()
            return _owned_convert_image(
                source,
                fmt,
                quality=SAVE_KW.get(fmt, {}).get("quality", 90),
                policy=_OwnedOutputPolicy(directory=_target_dir(source)),
                token=_OwnedCancelAdapter() if token is not None else None,
            )
        img = open_image(src)
        try:
            if getattr(img, "is_animated", False) and fmt in ("webp", "gif"):
                out = out_for(src, fmt)
                img.save(str(out), save_all=True, **{k: v for k, v in SAVE_KW[fmt].items()})
                return out
            return save_image(img, out_for(src, fmt), fmt)
        finally:
            img.close()
    return f


def image_to_jpeg(src, p):
    image = open_image(src)
    try:
        return save_image(image, out_for(src, "jpeg"), "jpg")
    finally:
        image.close()


def image_tool(tag, transform, keep_ext=True, fmt_override=None):
    def f(src, p):
        operation = {"rotated": "rotate", "flipped": "flip", "gray": "grayscale", "clean": "strip-metadata"}.get(tag)
        if operation and ext_of(src) not in ("svg", "psd", "dds", "jp2", "j2k", "jpx", "icns"):
            token = _token()
            return _owned_transform_image(
                src, operation,
                policy=_OwnedOutputPolicy(directory=_target_dir(Path(src)), suffix=f" {tag}"),
                token=_OwnedCancelAdapter() if token is not None else None,
            )
        img = open_image(src)
        img = transform(img, p)
        e = ext_of(src)
        fmt = fmt_override or ("jpg" if e == "jpeg" else "tiff" if e == "tif" else "heic" if e == "heif" else e)
        if fmt == "svg":
            fmt = "png"
        return save_image(img, out_for(src, fmt, tag), fmt)
    return f


# ---- Fix alignment (like a document scanner app): find the page's four corners, straighten it, clean it up
SCAN_LOOKS = ["Clean document", "Original colours", "Black & white", "Grayscale"]




















def image_scan(src,params):
    return _owned_scan_image(src,params,directory=_target_dir(Path(src)),token=_OwnedCancelAdapter() if _token() is not None else None)


def image_crop_resize(src, p):
    token = _token()
    return _owned_crop_resize_image(
        src, p,
        policy=_OwnedOutputPolicy(directory=_target_dir(Path(src)), suffix=" edited"),
        token=_OwnedCancelAdapter() if token is not None else None,
        background_remover=remove_bg_image if p.get("remove_bg") else None,
    )




def _strip(img, p):
    """A copy of the image without EXIF, ICC profile or any other attached metadata."""
    bare = img.copy()
    bare.info = {}
    return bare


def image_compress(src, p):
    token = _token()
    return _owned_compress_image(
        src,
        policy=_OwnedOutputPolicy(directory=_target_dir(Path(src)), suffix=" compressed"),
        token=_OwnedCancelAdapter() if token is not None else None,
    )




# ----------------------------------------------------------------------------
# Image extras (1.2): resize presets, upscale, sharpen, watermark, stitch, GIF,
# remove background (AI), blur faces, copy text (OCR)
# ----------------------------------------------------------------------------
def _asset(*parts) -> Path:
    """Path of a bundled resource, whether running from source or from the frozen app."""
    root = getattr(sys, "_MEIPASS", None) or Path(__file__).resolve().parent
    return Path(root, "assets", *parts)


RESIZE_PRESETS = ["50%", "25%", "1920 px (1080p)", "3840 px (4K)", "1080 × 1080", "1080 × 1350",
                  "< 1 MB", "< 500 KB"]


_SAVE_NAME = {"jpeg": "jpg", "tif": "tiff", "heif": "heic"}
_NOT_KEPT_AS_IS = {"pdf", "ico", "icns"}


def _same_fmt(src):
    """The format to save in so an edited image keeps its type (PNG when that type cannot be written back)."""
    raw = ext_of(src)
    name = _SAVE_NAME.get(raw, raw)
    return name if name in SAVE_KW and name not in _NOT_KEPT_AS_IS else "png"






def image_resize_preset(src, p):
    token = _token()
    return _owned_resize_preset_image(
        src, p.get("Output size", "50%"),
        policy=_OwnedOutputPolicy(directory=_target_dir(Path(src)), suffix=" resized"),
        token=_OwnedCancelAdapter() if token is not None else None,
    )




def image_upscale(src, p):
    token = _token()
    return _owned_enhance_image(src, "upscale",
                                policy=_OwnedOutputPolicy(directory=_target_dir(Path(src)), suffix=" 2x"),
                                token=_OwnedCancelAdapter() if token is not None else None)




def image_sharpen(src, p):
    token = _token()
    return _owned_enhance_image(src, "sharpen",
                                policy=_OwnedOutputPolicy(directory=_target_dir(Path(src)), suffix=" sharpened"),
                                token=_OwnedCancelAdapter() if token is not None else None)






WATERMARK_POSITIONS = ["Bottom right", "Bottom left", "Center", "Tiled"]


def image_watermark(src, p):
    token = _token()
    return _owned_watermark_image(
        src, p.get("Text", ""), p.get("Position", "Bottom right"),
        policy=_OwnedOutputPolicy(directory=_target_dir(Path(src)), suffix=" watermarked"),
        token=_OwnedCancelAdapter() if token is not None else None,
    )




def images_stitch(direction):
    def join(paths, p):
        pictures = [open_image(x).convert("RGBA") for x in paths]
        sheet = _imagekit.stitch(pictures, horizontal=direction == "h")
        fmt = "png" if _imagekit.any_transparent(pictures) else "jpg"
        return save_image(sheet, out_for(paths[0], fmt, "stitched"), fmt)
    return join



def images_to_gif(paths, p):
    raw = str(p.get("Seconds per image", "0.5")).replace(",", ".")
    try:
        seconds = _imagekit.clamp_seconds(float(raw))
    except ValueError:
        raise ConversionError("Seconds per image must be a number")
    box = _imagekit.gif_box(open_image(paths[0]).size)
    frames = []
    for path in paths:
        check_cancel()
        frames.append(_imagekit.gif_frame(open_image(path), box))
    out = out_for(paths[0], "gif", "animated")
    frames[0].save(str(out), save_all=True, append_images=frames[1:], duration=int(seconds * 1000), loop=0, optimize=True)
    return out



# ---- AI models (downloaded once, then offline)
MODELS = {
    # reads video/audio links from YouTube and ~1800 other sites; always the latest version, self-updating
    "yt-dlp": {"file": "yt-dlp.exe", "size": 0, "sha256": "", "mb": 18,
               "url": "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"},
    # Send to phone → Link from this PC: Cloudflare's free tunnel tool (no account), serves a file from this PC
    "cloudflared": {"file": "cloudflared.exe", "size": 0, "sha256": "", "mb": 60,
                    "url": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"},
    # speech recognition (whisper.cpp), multilingual incl. Arabic; size/sha256 unknown upfront -> Content-Length check
    "whisper-small": {"file": "ggml-small-q5_1.bin", "size": 0, "sha256": "", "mb": 190,
                      "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small-q5_1.bin"},
    "isnet": {"file": "isnet-general-use.onnx", "size": 178648008,
              "sha256": "60920e99c45464f2ba57bee2ad08c919a52bbf852739e96947fbb4358c0d964a",
              "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-general-use.onnx"},
}


def models_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    d = Path(base) / "ConvertANNY" / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def model_path(name) -> Path:
    bundled = _asset("models", MODELS[name]["file"])
    return bundled if bundled.is_file() else models_dir() / MODELS[name]["file"]


def _complete_marker(model_file: Path) -> Path:
    return model_file.with_name(model_file.name + ".ok")


def model_ready(name) -> bool:
    """Whether a model is fully downloaded: right size when known, else the completion marker exists."""
    target = model_path(name)
    if not target.is_file():
        return False
    expected = MODELS[name]["size"]
    if expected:
        return target.stat().st_size == expected
    return _complete_marker(target).is_file()


def mark_model_ready(name):
    """Record that a size-less model finished downloading (sized models are verified by size instead)."""
    target = model_path(name)
    if MODELS[name]["size"] or not target.is_file():
        return
    _complete_marker(target).write_text("ok", encoding="utf-8")


def remove_bg_image(img):
    """The subject of a PIL image on a transparent background (AI model, offline)."""
    token = _OwnedCancelAdapter() if _token() is not None else None
    return _owned_remove_background(img, model_path("isnet"), token=token)


def image_remove_bg(src, p):
    source = open_image(src)
    output = None
    try:
        output = remove_bg_image(source)
        return save_image(output, out_for(src, "png", "no background"), "png")
    finally:
        source.close()
        if output is not None and output is not source:
            output.close()


def image_blur_faces(src, p):
    from convertanny_core import face_blur
    original = open_image(src)
    opaque = _flatten(original)
    search_copy, scale = face_blur.shrink_for_detection(opaque)
    found = detect_faces(search_copy)
    if not found:
        raise ConversionError("No faces found in this image")
    canvas = original.convert("RGBA") if original.mode in ("RGBA", "LA") else opaque.copy()
    face_blur.blur_faces(canvas, found, scale)
    fmt = _same_fmt(src)
    return save_image(canvas, out_for(src, fmt, "blurred"), fmt)



OCR_PS = r"""
param([string]$Path)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Path)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$dec = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bmp = Await ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$best = ''; $bestScore = -1
foreach ($lang in [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages) {
    $eng = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
    if ($eng -eq $null) { continue }
    $res = Await ($eng.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
    $txt = ($res.Lines | ForEach-Object { $_.Text }) -join "`n"
    $score = ([regex]::Matches($txt, '\p{L}{2,}')).Count
    if ($score -gt $bestScore) { $best = $txt; $bestScore = $score }
}
Write-Output $best
"""


def image_ocr(src, p):
    """Copy text (OCR) with the text recognizer built into Windows 10/11, for every language installed."""
    if not IS_WIN:
        raise ConversionError("Copying text from images needs Windows 10 or 11")
    try:
        return _owned_ocr(src, out_for(src, "txt", "text"), windows=True,
                          open_image=open_image, flatten=_flatten, image_module=_pil,
                          script_text=OCR_PS, creation_flags=NO_WINDOW, run=subprocess.run)
    except _OwnedConversionError as error:
        raise ConversionError(str(error)) from error


def images_to_pdf(paths, p):
    token = _token()
    source = Path(paths[0])
    return _owned_images_to_pdf(
        paths,
        policy=_OwnedOutputPolicy(directory=_target_dir(source), suffix=" combined" if len(paths) > 1 else ""),
        token=_OwnedCancelAdapter() if token is not None else None,
    )




# ----------------------------------------------------------------------------
# PDF / EPUB  (PyMuPDF)
# ----------------------------------------------------------------------------
def close_pdfs():
    """Close the PDFs this thread opened (called after every job)."""
    _pdf_handles.close_all()



def _mu():
    """PyMuPDF whose opened documents are closed by close_pdfs() when the job ends."""
    return _pdf_handles.TrackedPyMuPDF()



def pdf_to_images(fmt, dpi=200):
    def f(src, p):
        token = _token()
        return _owned_pdf_to_images(
            src, fmt, dpi=dpi, directory=_target_dir(Path(src)),
            token=_OwnedCancelAdapter() if token is not None else None,
        )
    return f




def pdf_to_text(src, p):
    token = _token()
    return _owned_pdf_to_text(src, policy=_OwnedOutputPolicy(directory=_target_dir(Path(src))),
                              token=_OwnedCancelAdapter() if token is not None else None)




def pdf_to_markdown(src, p):
    token = _token()
    return _owned_pdf_to_markdown(src, policy=_OwnedOutputPolicy(directory=_target_dir(Path(src))),
                                  token=_OwnedCancelAdapter() if token is not None else None)




def pdf_to_html(src, p):
    token = _token()
    return _owned_pdf_to_html(src, policy=_OwnedOutputPolicy(directory=_target_dir(Path(src))),
                              token=_OwnedCancelAdapter() if token is not None else None)






def pdf_to_docx(src, p):
    token = _token()
    return _owned_pdf_to_docx_pages(src, policy=_OwnedOutputPolicy(directory=_target_dir(Path(src))),
                                    token=_OwnedCancelAdapter() if token is not None else None)




def pdf_to_docx_flow(src, p):
    token = _token()
    return _owned_pdf_to_docx(src, policy=_OwnedOutputPolicy(directory=_target_dir(Path(src))),
                              token=_OwnedCancelAdapter() if token is not None else None)


def pdf_to_xlsx(src, p):
    token = _token()
    return _owned_pdf_to_xlsx(src, policy=_OwnedOutputPolicy(directory=_target_dir(Path(src))),
        token=_OwnedCancelAdapter() if token is not None else None)






def pdf_compress(src, p):
    token = _token()
    return _owned_compress_pdf(src,
        policy=_OwnedOutputPolicy(directory=_target_dir(Path(src)), suffix=" compressed"),
        token=_OwnedCancelAdapter() if token is not None else None)




def pdf_split(src, p):
    token = _token()
    return _owned_split_pdf(src, directory=_target_dir(Path(src)),
        token=_OwnedCancelAdapter() if token is not None else None)






def pdf_extract_pages(src, p):
    token = _token()
    return _owned_extract_pdf_pages(src, p["Pages (e.g. 1-3,5)"],
        policy=_OwnedOutputPolicy(directory=_target_dir(Path(src)), suffix=" pages"),
        token=_OwnedCancelAdapter() if token is not None else None)




def pdf_rotate(src, p):
    token = _token()
    return _owned_rotate_pdf(src, 90,
        policy=_OwnedOutputPolicy(directory=_target_dir(Path(src)), suffix=" rotated"),
        token=_OwnedCancelAdapter() if token is not None else None)




def pdf_extract_images(src, p):
    token = _token()
    return _owned_extract_pdf_images(src, directory=_target_dir(Path(src)),
        token=_OwnedCancelAdapter() if token is not None else None)




def pdf_merge(paths, p):
    token = _token()
    return _owned_merge_pdfs(paths,
        policy=_OwnedOutputPolicy(directory=_target_dir(Path(paths[0])), suffix=" merged"),
        token=_OwnedCancelAdapter() if token is not None else None)


def pdf_protect(src, p):
    token = _token()
    return _owned_protect_pdf(src, p.get("Password", ""),
        policy=_OwnedOutputPolicy(directory=_target_dir(Path(src)), suffix=" protected"),
        token=_OwnedCancelAdapter() if token is not None else None)


# ---- 1.2: more PDF tools -------------------------------------------------------------------------




PAGE_NUMBER_POSITIONS = ["Bottom center", "Bottom right", "Bottom left", "Top center", "Top right", "Top left"]
PAGE_NUMBER_STYLES = ["1", "1 / 12", "Page 1 of 12", "١", "صفحة ١ من ١٢"]


def pdf_page_numbers(src, p):
    token = _token()
    return _owned_number_pdf_pages(src, p.get("Position", PAGE_NUMBER_POSITIONS[0]),
        p.get("Style", PAGE_NUMBER_STYLES[0]),
        policy=_OwnedOutputPolicy(directory=_target_dir(Path(src)), suffix=" numbered"),
        token=_OwnedCancelAdapter() if token is not None else None)


WATERMARK_DEFAULT = {"text": "CONFIDENTIAL", "angle": 45, "opacity": 0.22, "size": 0.8, "color": "#808080"}






def pdf_watermark(paths, p):
    token = _token()
    paths = paths if isinstance(paths, (list, tuple)) else [paths]
    pdfs = [path for path in paths if EXT_CATEGORY.get(ext_of(path)) == "pdf"]
    if not pdfs:
        return []
    logo = next((path for path in paths if EXT_CATEGORY.get(ext_of(path)) == "image"), None)
    try:
        spec = dict(WATERMARK_DEFAULT, **json.loads(p.get("Watermark") or "{}"))
    except (ValueError, TypeError):
        spec = dict(WATERMARK_DEFAULT)
    if p.get("Text"):
        spec["text"] = p["Text"]
    return [_owned_watermark_pdf(pdf, spec.get("text", "CONFIDENTIAL"), logo=logo,
        angle=spec.get("angle", 45), opacity=spec.get("opacity", 0.22), size=spec.get("size", 0.8),
        color=spec.get("color", "#808080"),
        policy=_OwnedOutputPolicy(directory=_target_dir(Path(pdf)), suffix=" watermarked"),
        token=_OwnedCancelAdapter() if token is not None else None) for pdf in pdfs]


def pdf_grayscale(src, p):
    token = _token()
    return _owned_grayscale_pdf(src,
        policy=_OwnedOutputPolicy(directory=_target_dir(Path(src)), suffix=" grayscale"),
        token=_OwnedCancelAdapter() if token is not None else None)


_enc_cache: dict = {}


def pdf_is_encrypted(path) -> bool:
    """Whether a PDF needs a password to open or is encrypted; cached per file version. False if unreadable."""
    try:
        version = (str(path), os.path.getmtime(path))
        known = _enc_cache.get(version)
        if known is None:
            document = _mu().open(str(path))
            try:
                known = bool(document.needs_pass or document.is_encrypted)
            finally:
                document.close()
            _enc_cache[version] = known
        return known
    except Exception:
        return False


def pdf_unlock(src, p):
    token = _token()
    return _owned_unlock_pdf(src, p.get("Password", ""),
        policy=_OwnedOutputPolicy(directory=_target_dir(Path(src)), suffix=" unlocked"),
        token=_OwnedCancelAdapter() if token is not None else None)


def _image_pdf_page(path):
    """Create a print-sized PDF page for a raster image, flattening transparency to white."""
    from convertanny_core.pdf_images import image_page_bytes
    image = _flatten(open_image(path))
    return _mu().open("pdf", image_page_bytes(image, dpi=150))


def pdf_arrange(paths, p):
    paths = paths if isinstance(paths, (list, tuple)) else [paths]
    try:
        plan = json.loads(str(p.get("Layout", "")))
        sources, pages = plan["sources"], plan["pages"]
    except (ValueError, KeyError, TypeError):
        sources, pages = [paths[0]], [[0, int(a), int(b)] for a, b in
            (item.split(":") for item in str(p.get("Layout", "")).split(",") if ":" in item)]
    token = _token()
    return _owned_arrange_pdf(sources, pages,
        policy=_OwnedOutputPolicy(directory=_target_dir(Path(sources[0])), suffix=" arranged"),
        token=_OwnedCancelAdapter() if token is not None else None)


def pdf_sign(paths, p):
    token = _token()
    paths = paths if isinstance(paths, (list, tuple)) else [paths]
    pdf = next((path for path in paths if EXT_CATEGORY.get(ext_of(path)) == "pdf"), None)
    if not pdf:
        raise ConversionError("Choose a PDF file to sign")
    try:
        spec = json.loads(p.get("Sign") or "{}")
    except (ValueError, TypeError):
        spec = {}
    signature = spec.get("sig")
    placements = spec.get("places") or [{"page": spec.get("page", 0),
        "rect": spec.get("rect", [0.6, 0.8, 0.9, 0.9])}]
    return _owned_sign_pdf(pdf, signature, placements,
        policy=_OwnedOutputPolicy(directory=_target_dir(Path(pdf)), suffix=" signed"),
        token=_OwnedCancelAdapter() if token is not None else None)


def count_words(src, p):
    return _owned_document_stats(src)


def epub_to_pdf(src, p):
    token = _token()
    return _owned_ebook_to_pdf(
        src, policy=_OwnedOutputPolicy(directory=_target_dir(Path(src))),
        token=_OwnedCancelAdapter() if token is not None else None,
    )


def epub_to_text(src, p):
    token = _token()
    return _owned_ebook_to_text(
        src, policy=_OwnedOutputPolicy(directory=_target_dir(Path(src))),
        token=_OwnedCancelAdapter() if token is not None else None,
    )


# ----------------------------------------------------------------------------
# Text documents (Markdown / TXT / HTML) — pure Python
# ----------------------------------------------------------------------------
HTML_CSS = HTML_DOCUMENT_CSS


def _read_text(src) -> str:
    """Read a local document with the product's BOM and legacy-code-page handling."""
    from convertanny_core.text_decode import read_document
    return read_document(src)


def _to_html(src) -> str:
    e = ext_of(src)
    txt = _read_text(src)
    if e in ("md", "markdown"):
        import markdown
        return markdown.markdown(txt, extensions=["extra", "sane_lists", "tables"])
    if e in ("html", "htm"):
        m = re.search(r"<body[^>]*>(.*)</body>", txt, re.S | re.I)
        return m.group(1) if m else txt
    import html
    return "<div style='font-family:Helvetica,Arial,sans-serif;font-size:11pt;line-height:1.5'>" + html.escape(txt).replace('\n','<br>') + "</div>"


def html_to_pdf_file(html_body: str, out: Path) -> Path:
    return _owned_html_to_pdf(html_body, out)


def text_to_pdf(src, p):
    token = _token()
    return _owned_text_to_pdf(src, markdown=ext_of(src) in ("md", "markdown"),
        policy=_OwnedOutputPolicy(directory=_target_dir(Path(src))),
        token=_OwnedCancelAdapter() if token is not None else None)

def text_markdown_to_pdf(src, p):
    token = _token()
    return _owned_text_to_pdf(src, markdown=True,
        policy=_OwnedOutputPolicy(directory=_target_dir(Path(src)), suffix=" formatted"),
        token=_OwnedCancelAdapter() if token is not None else None)


def text_to_html(src, p):
    token = _token()
    return _owned_text_to_html(src,
        policy=_OwnedOutputPolicy(directory=_target_dir(Path(src))),
        token=_OwnedCancelAdapter() if token is not None else None)


def html_to_markdown(src, p):
    token = _token()
    return _owned_html_to_markdown(src,
        policy=_OwnedOutputPolicy(directory=_target_dir(Path(src))),
        token=_OwnedCancelAdapter() if token is not None else None)


def md_to_txt(src, p):
    token = _token()
    return _owned_markdown_to_text(src,
        policy=_OwnedOutputPolicy(directory=_target_dir(Path(src))),
        token=_OwnedCancelAdapter() if token is not None else None)


def text_to_docx(src, p):
    token = _token()
    return _owned_text_to_docx(src,
        policy=_OwnedOutputPolicy(directory=_target_dir(Path(src))),
        token=_OwnedCancelAdapter() if token is not None else None)


# ----------------------------------------------------------------------------
# Office (Word / Excel / PowerPoint via COM, or LibreOffice)
# ----------------------------------------------------------------------------












def office_available():
    return _owned_office_available()


def office_convert(src,fmt):
    try:
        return _owned_office_convert(src,fmt,directory=_target_dir(Path(src)),token=_OwnedCancelAdapter() if _token() is not None else None)
    except _OwnedConversionError as error:
        raise ConversionError(str(error)) from error


def _com_convert(src,fmt):
    try:
        return _owned_office_convert(src,fmt,directory=_target_dir(Path(src)),native_only=True,token=_OwnedCancelAdapter() if _token() is not None else None)
    except _OwnedConversionError:
        return None


def office_to(fmt):
    def convert(src, _params):
        return office_convert(src, fmt)
    return convert


def slides_to_images(fmt):
    return _owned_slide_image_converter(
        fmt, native_enabled=IS_WIN, native_export=_com_convert,
        document_export=office_convert, rasterizer=pdf_to_images,
        output_directory=out_dir_for, output_file=out_for,
    )


# ----------------------------------------------------------------------------
# Spreadsheets (openpyxl / csv)
# ----------------------------------------------------------------------------
















def _table_operation(source, operation, target_format=None):
    source = Path(source)
    intermediate = None
    try:
        if source.suffix.lower() not in (".csv", ".tsv", ".xlsx", ".xlsm"):
            intermediate = office_convert(source, "xlsx")
        token = _OwnedCancelAdapter() if _token() is not None else None
        arguments = [intermediate or source]
        if target_format is not None:
            arguments.append(target_format)
        return operation(*arguments, directory=_target_dir(source), token=token)
    finally:
        if intermediate is not None:
            Path(intermediate).unlink(missing_ok=True)


def sheet_to_delimited(fmt):
    return lambda source, params: _table_operation(source, _owned_table_to_delimited, fmt)


def sheet_to_xlsx(source, params):
    return _table_operation(source, _owned_table_to_xlsx)


def sheet_to_json(source, params):
    return _table_operation(source, _owned_table_to_json)


def sheet_to_html(source, params):
    return _table_operation(source, _owned_table_to_html)


def sheet_to_markdown(source, params):
    return _table_operation(source, _owned_table_to_markdown)


def sheet_to_pdf(src, p):
    return _owned_sheet_to_pdf(
        src, native_available=office_available, native_export=office_convert,
        html_export=sheet_to_html, html_content=_to_html, html_render=html_to_pdf_file,
        output=out_for(src, "pdf"), native_error=ConversionError,
    )


# ----------------------------------------------------------------------------
# Subtitles
# ----------------------------------------------------------------------------
def srt_to_vtt(src, p):
    return _owned_convert_subtitle(src, "vtt", directory=_target_dir(Path(src)))


def vtt_to_srt(src, p):
    return _owned_convert_subtitle(src, "srt", directory=_target_dir(Path(src)))


def subs_ffmpeg(fmt):
    def convert(src, p):
        return _owned_convert_subtitle(src, fmt, directory=_target_dir(Path(src)))
    return convert


def subs_to_txt(src, p):
    return _owned_subtitle_to_text(src, directory=_target_dir(Path(src)))


# ----------------------------------------------------------------------------
# Archives
#   read : zip, 7z, tar, tar.gz/tgz, tar.bz2/tbz2, tar.xz/txz, gz, bz2, xz  (built in)
#          rar (+ iso, cab…) via 7-Zip, WinRAR, or Windows' own tar.exe
#   write: zip, 7z, tar, tar.gz, tar.bz2, tar.xz (built in), rar (needs WinRAR)
# ----------------------------------------------------------------------------
ARCHIVE_OUT = ["zip", "7z", "rar", "tar", "tar.gz", "tar.bz2", "tar.xz"]
ARCHIVE_LABEL = {"zip": "ZIP", "7z": "7Z", "rar": "RAR", "tar": "TAR", "tar.gz": "TAR.GZ",
                 "tar.bz2": "TAR.BZ2", "tar.xz": "TAR.XZ"}
# ext_of() value -> canonical archive format
ARCHIVE_FMT = {"zip": "zip", "7z": "7z", "rar": "rar", "tar": "tar", "tgz": "tar.gz", "tbz2": "tar.bz2",
               "txz": "tar.xz", "gz": "gz", "bz2": "bz2", "xz": "xz", "iso": "iso", "cab": "cab",
               "cbz": "zip", "cbr": "rar", "cb7": "7z", "cbt": "tar"}










def can_write_rar() -> bool:
    return _owned_can_write_rar()






# ---- comic books (.cbz zip, .cbr rar, .cb7 7z, .cbt tar: a folder of page pictures)
_COMIC_IMG = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif", ".jxl", ".tif", ".tiff")


_DIGIT_RUN = re.compile(r"(\d+)")


def _natural(s):
    """Sort key that orders embedded numbers by value ("p2" before "p10"), ignoring case."""
    return [int(piece) if piece.isdigit() else piece.lower() for piece in _DIGIT_RUN.split(str(s))]


def comic_pages(src) -> list[Path]:
    """The page pictures of a comic book, in reading order (extracted to a temp folder)."""
    src = Path(src)
    tmp = temp_dir()
    _owned_extract_archive_into(src, tmp, _OwnedCancelAdapter() if _token() is not None else None)
    pages = sorted((f for f in tmp.rglob("*") if f.is_file() and f.suffix.lower() in _COMIC_IMG
                    and "__MACOSX" not in f.parts and not f.name.startswith(".")),
                   key=lambda f: _natural(f.relative_to(tmp)))
    if not pages:
        raise ConversionError("No pages found in this comic book")
    return pages


def _append_page(book, mu, picture_file):
    """Add one picture to a PDF, using Pillow when MuPDF cannot read the format (e.g. AVIF)."""
    try:
        book.insert_pdf(mu.open("pdf", mu.open(str(picture_file)).convert_to_pdf()))
    except Exception:
        book.insert_pdf(_image_pdf_page(picture_file))


def _pages_to_pdf(pages, out):
    mu = _mu()
    book = mu.open()
    for picture in pages:
        check_cancel()
        _append_page(book, mu, picture)
    book.save(str(out), garbage=3, deflate=True)
    return out


def _numbered_pages(pages):
    """(source, archive name) pairs: zero-padded sequence numbers keep the reading order."""
    width = max(3, len(str(len(pages))))
    return [(page, f"{number:0{width}d}{page.suffix.lower()}") for number, page in enumerate(pages, 1)]


def _pages_to_cbz(pages, out):
    # Pictures are already compressed, so entries are stored rather than deflated.
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as book:
        for page, entry in _numbered_pages(pages):
            check_cancel()
            book.write(page, entry)
    return out


def _comic_converter(ext, writer):
    def convert(src, _params):
        return writer(comic_pages(src), out_for(src, ext))
    return convert


def comic_to_pdf(src, p):
    return _comic_converter("pdf", _pages_to_pdf)(src, p)


def comic_to_cbz(src, p):
    return _comic_converter("cbz", _pages_to_cbz)(src, p)


def comic_extract(src, p):
    pages = comic_pages(src)
    folder = out_dir_for(src, "pages")
    folder.mkdir()
    for page, entry in _numbered_pages(pages):
        shutil.copy2(page, folder / entry)
    return folder


def images_to_cbz(paths, p):
    ordered = sorted(map(Path, paths), key=lambda item: _natural(item.name))
    return _pages_to_cbz(ordered, out_for(ordered[0], "cbz", "comic"))


def pdf_to_cbz(src, p):
    token = _OwnedCancelAdapter() if _token() is not None else None
    return _owned_pdf_to_cbz(src, out_for(src, "cbz"), open_document=_mu().open, token=token)


def archive_extract(src, p):
    token = _OwnedCancelAdapter() if _token() is not None else None
    folder = _owned_extract_archive(src, directory=_target_dir(Path(src)), token=token)
    items = list(folder.iterdir())
    if len(items) == 1 and items[0].is_dir():
        inner = items[0]
        staging = folder.with_name(folder.name + ".__move")
        inner.rename(staging)
        folder.rmdir()
        final = unique_path(folder.parent / inner.name)
        staging.rename(final)
        return final
    return _remember(folder)




def archive_repack(fmt):
    """Convert one archive format to another (extract to temp, repack)."""
    def f(src, p):
        src = Path(src)
        token = _OwnedCancelAdapter() if _token() is not None else None
        out = _owned_repack_archive(src, fmt, directory=_target_dir(src), token=token,
                                    on_temporary=lambda path: _remember(path, "tmp"))
        return _remember(out)
    return f


def pack_paths(paths, fmt) -> Path:
    """Compress files/folders into one archive next to the first item."""
    items = [Path(x) for x in paths]
    if not items:
        raise ConversionError("Choose files or folders to archive")
    token = _OwnedCancelAdapter() if _token() is not None else None
    out = _owned_create_archive(items, fmt, directory=_target_dir(items[0]), token=token)
    return _remember(out)


def _packer(fmt):
    """A conversion callback that packs the selected paths into one archive of `fmt`."""
    def run_pack(paths, _params):
        return pack_paths(paths, fmt)
    return run_pack


def compress_to(fmt):
    return _packer(fmt)


def pack(folder_or_files, fmt: str, name_like: Path | None = None) -> Path:   # kept for older callers
    chosen = folder_or_files if isinstance(folder_or_files, list) else [folder_or_files]
    return pack_paths(chosen, fmt)


def to_zip(paths, p):
    return _packer("zip")(paths, p)


def to_targz(paths, p):
    return _packer("tar.gz")(paths, p)


def gzip_file(src, p):
    token = _OwnedCancelAdapter() if _token() is not None else None
    return _remember(_owned_gzip_file(src, directory=_target_dir(Path(src)), token=token))


# ---- 1.2: files & archives ---------------------------------------------------------------------
SPLIT_SIZES = ["10 MB", "25 MB (email)", "100 MB", "700 MB (CD)", "4 GB (USB stick, FAT32)"]


def _size_bytes(label) -> int:
    """Bytes in a size label such as "25 MB" or "1.5 GB"; anything not GB is read as MB."""
    amount, unit = str(label).split()[:2]
    scale = 1024 ** 3 if unit.upper().startswith("GB") else 1024 ** 2
    return int(float(amount) * scale)


def split_parts(paths, params):
    selection = [Path(path) for path in (paths if isinstance(paths,(list,tuple)) else [paths])]
    if not selection:
        raise ConversionError("Choose files to split")
    first = selection[0]
    temporary = None
    if len(selection)==1 and first.is_file() and EXT_CATEGORY.get(ext_of(first)) in ("archive","video","audio"):
        source = first
    else:
        temporary = pack_paths(selection,"zip")
        source = temporary
    try:
        token = _OwnedCancelAdapter() if _token() is not None else None
        outputs = _owned_split_file(source,_size_bytes(params.get("Part size",SPLIT_SIZES[1])),
                                   directory=_target_dir(first),token=token)
        return [_remember(output) for output in outputs]
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def is_part_file(path):
    return _owned_is_part_file(path)


def join_parts(paths, params):
    if not paths:
        raise ConversionError("Choose a numbered file part")
    first = Path(paths[0])
    token = _OwnedCancelAdapter() if _token() is not None else None
    return _remember(_owned_join_files(first,directory=_target_dir(first),token=token))


PROTECT_FORMATS = ["ZIP (AES-256)", "7Z (AES-256, hides file names)"]


def protect_archive(paths, p):
    paths = list(paths) if isinstance(paths, (list, tuple)) else [paths]
    source = Path(paths[0])
    output = _owned_create_protected_archive(
        paths, p.get("Format", PROTECT_FORMATS[0]), p.get("Password", ""),
        directory=_target_dir(source), token=_OwnedCancelAdapter() if _token() else None)
    return _remember(output)


# ConvertANNY font operations

def font_to(fmt):
    def convert(src, params):
        token = _OwnedCancelAdapter() if _token() is not None else None
        return _remember(_owned_convert_font(src, fmt, directory=_target_dir(Path(src)), token=token))
    return convert


def font_install(src, params):
    token = _OwnedCancelAdapter() if _token() is not None else None
    return _owned_install_font(src, token=token)


# Arabic text that shows as Ø§Ù„... or as ??? / boxes




def fix_arabic_text(src, p):
    source=Path(src)
    return _owned_repair_arabic_file(source, policy=_OwnedOutputPolicy(
        directory=_target_dir(source), suffix=" fixed"))


def archive_targets(exclude: str = "") -> list[str]:
    return [f for f in ARCHIVE_OUT if f != exclude]


def _rar_hint(f):
    if f == "rar" and not can_write_rar():
        return "needs WinRAR"
    return ""


# ----------------------------------------------------------------------------
# Catalog
# ----------------------------------------------------------------------------
@dataclass
class Op:
    id: str
    label: str
    fn: Callable
    group: str = "convert"           # convert | tool | action
    ask: list[tuple[str, str]] = field(default_factory=list)  # [(field, default)]
    multi: bool = False              # fn receives the whole list of paths
    hint: str = ""
    ui: str = ""                     # "crop" -> the app opens the crop & resize editor first
    model: str = ""                  # AI model the op needs (downloaded once, with consent)


IMAGE_OUT = ["png", "jpg", "webp", "heic", "avif", "tiff", "bmp", "gif", "ico", "tga", "jp2", "icns", "pdf"]
VIDEO_OUT = ["mp4", "mov", "mkv", "webm", "avi", "wmv"]
AUDIO_OUT = ["mp3", "m4a", "wav", "flac", "ogg", "opus", "aiff", "wma", "ac3"]
SUB_OUT = ["srt", "vtt", "ass"]


def _norm(e):
    value = str(e).casefold().lstrip(".")
    aliases = (("jpg", {"jpeg"}), ("tiff", {"tif"}), ("heic", {"heif"}),
               ("html", {"htm"}), ("md", {"markdown"}), ("aiff", {"aif"}),
               ("ogg", {"oga"}), ("mp4", {"m4v"}), ("jp2", {"j2k", "jpx"}),
               ("ass", {"ssa"}))
    return next((canonical for canonical, variants in aliases if value in variants), value)


def conversions(paths: list[str]) -> list[Op]:
    cat = category_of(paths)
    e = _norm(ext_of(paths[0])) if paths else ""
    ops: list[Op] = []
    add = lambda fmt, fn, label=None: ops.append(Op(f"to_{fmt}", label or fmt.upper(), fn)) if fmt != e else None

    if cat == "image":
        for f in IMAGE_OUT:
            if f == "pdf":
                ops.append(Op("to_pdf", "PDF", images_to_pdf, multi=True))
            elif f == "jpg" and ext_of(paths[0]) == "jpeg":     # .jpeg → .jpg
                ops.append(Op("to_jpg", "JPG", image_to("jpg")))
            else:
                add(f, image_to(f))
            if f == "jpg" and ext_of(paths[0]) != "jpeg":    # the same picture type, as .jpeg
                ops.append(Op("to_jpeg", "JPEG", image_to_jpeg))
    elif cat == "video":
        for f in VIDEO_OUT:
            if f == "mkv":                                   # MKV in both picture codecs
                ops.append(Op("to_mkv", "MKV H.264", video_to("mkv")))
                ops.append(Op("to_mkv_hevc", "MKV H.265", video_to("mkv_hevc"), hint="smaller file"))
            else:
                add(f, video_to(f))
        ops.append(Op("to_hevc", "MP4 H.265", video_to_hevc, hint="smaller file"))
        add("gif", video_to_gif)
        ops.append(Op("to_mp3", "MP3", audio_to("mp3"), hint="audio only"))
        ops.append(Op("to_m4a", "M4A", audio_to("m4a"), hint="audio only"))
    elif cat == "audio":
        for f in AUDIO_OUT:
            add(f, audio_to(f))
    elif cat == "pdf":
        ops.append(Op("to_docx", "DOCX", pdf_to_docx, hint="same look"))
        ops.append(Op("to_docx_flow", "DOCX", pdf_to_docx_flow, hint="flowing text"))
        ops.append(Op("to_xlsx", "XLSX", pdf_to_xlsx, hint="extract PDF tables"))
        add("png", pdf_to_images("png"))
        add("jpg", pdf_to_images("jpg"))
        add("txt", pdf_to_text)
        add("md", pdf_to_markdown, "Markdown")
        add("html", pdf_to_html)
        add("cbz", pdf_to_cbz, "CBZ")
    elif cat == "document":
        if e in ("md", "txt", "html"):
            add("pdf", text_to_pdf)
            if e == 'txt':
                ops.append(Op('to_pdf_markdown','PDF · Markdown',text_markdown_to_pdf,hint='Render headings, bold text and lists'))
            add("html", text_to_html)
            if e == "html":
                add("md", html_to_markdown, "Markdown")
            if e == "md":
                add("txt", md_to_txt)
            if office_available():
                add("docx", text_to_docx)
        else:  # docx / doc / rtf / odt
            for f in ("pdf", "docx", "doc", "odt", "rtf", "txt", "html"):     # DOC for older Word
                add(f, office_to(f))
    elif cat == "slides":
        add("pdf", office_to("pdf"))
        add("png", slides_to_images("png"))
        add("jpg", slides_to_images("jpg"))
        if e != "pptx":
            add("pptx", office_to("pptx"))
        add("ppt", office_to("ppt"))                         # older PowerPoint
        add("odp", office_to("odp"))
    elif cat == "spreadsheet":
        add("xlsx", sheet_to_xlsx)
        add("csv", sheet_to_delimited("csv"))
        add("tsv", sheet_to_delimited("tsv"))
        add("json", sheet_to_json)
        add("html", sheet_to_html)
        add("md", sheet_to_markdown, "Markdown")
        add("pdf", sheet_to_pdf)
        if office_available():
            add("xls", office_to("xls"))                     # older Excel
            add("ods", office_to("ods"))
    elif cat == "subtitle":
        for f in SUB_OUT:
            if f == e:
                continue
            if e == "srt" and f == "vtt":
                add("vtt", srt_to_vtt)
            elif e == "vtt" and f == "srt":
                add("srt", vtt_to_srt)
            else:
                add(f, subs_ffmpeg(f))
        add("txt", subs_to_txt)
    elif cat == "font":
        for f in ("ttf", "woff", "woff2", "otf"):
            if f != e and not (f == "otf" and e == "ttf"):        # TrueType -> CFF isn't a clean conversion
                add(f, font_to(f), f.upper())
    elif cat == "comic":
        add("pdf", comic_to_pdf)
        if e != "cbz":
            add("cbz", comic_to_cbz, "CBZ")
    elif cat == "ebook":
        add("pdf", epub_to_pdf)
        add("txt", epub_to_text)
        add("md", pdf_to_markdown, "Markdown")
        add("html", pdf_to_html)
        if e in ("xps", "oxps"):
            add("png", pdf_to_images("png", dpi=150))
            add("jpg", pdf_to_images("jpg", dpi=150))
    elif cat == "archive":                 # "Extract" lives in Tools
        cur = ARCHIVE_FMT.get(ext_of(paths[0]), "")
        for f in archive_targets(exclude=cur):
            ops.append(Op(f"to_{f}", ARCHIVE_LABEL[f], archive_repack(f), hint=_rar_hint(f)))
    elif cat in ("folder", "mixed", "other"):
        for f in archive_targets():
            ops.append(Op(f"to_{f}", ARCHIVE_LABEL[f], compress_to(f), multi=True, hint=_rar_hint(f)))
        if cat == "other" and len(paths) == 1:
            ops.append(Op("to_gz", "GZIP", gzip_file))
    return ops


TRIM = [("Start", "0:00"), ("End", "0:30")]


def _user_name() -> str:
    for key in ("USERNAME", "USER"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    try:
        import getpass
        return getpass.getuser().strip()
    except (OSError, RuntimeError):
        return ""


def tools(paths: list[str]) -> list[Op]:
    from convertanny_core.tool_catalog import tools_for
    return tools_for(paths, globals())


# ============================================================================
# Make it yours: presets and chains (defined by the user in Settings, carried to the job as a spec)
# ============================================================================
PRESET_IMAGE_FORMATS = ["webp", "jpg", "png", "avif", "heic"]
PRESET_VIDEO_FORMATS = ["mp4", "webm", "mkv"]
PRESET_VIDEO_HEIGHTS = [0, 2160, 1440, 1080, 720, 480, 360]


def image_preset(src, p):
    from convertanny_core.profiles import image_profile
    return image_profile(src, p.get('_spec') or {}, directory=_target_dir(Path(src)),
                         token=_OwnedCancelAdapter() if _token() is not None else None)


def video_preset(src, p):
    from convertanny_core.profiles import video_profile
    return video_profile(src, p.get('_spec') or {}, ffmpeg=ffmpeg(), directory=_target_dir(Path(src)),
                         token=_OwnedCancelAdapter() if _token() is not None else None)


_SAMPLE_EXT = {"image": "jpg", "video": "mp4", "audio": "mp3", "pdf": "pdf", "document": "docx", "slides": "pptx",
               "spreadsheet": "xlsx", "archive": "zip", "ebook": "epub", "comic": "cbz", "font": "ttf",
               "subtitle": "srt", "other": "bin"}


def _fake_path(category: str, ext: str = "") -> str:
    """A pretend file name for a type, to ask which slices exist for it."""
    return f"C:/example/file.{ext or _SAMPLE_EXT.get(category, 'bin')}"


_NOT_CHAINABLE = ("none", "count", "unlock")


def _runs_unattended(op) -> bool:
    """True when an operation can run inside a saved chain: no dialog, no on-screen picking, not a one-off."""
    if op.ui or op.id in _NOT_CHAINABLE:
        return False
    return not any(str(default).startswith("@") for _, default in op.ask)


def chain_step_ops(ext: str) -> list[Op]:
    """Steps a chain can use on a file with this extension: conversions and tools that need no picking on screen."""
    sample = [_fake_path("", ext)]
    return [op for op in conversions(sample) + tools(sample) if _runs_unattended(op)]


_FIXED_RESULT = {"zip": "zip", "protect_zip": "zip", "removebg": "png"}


def _step_ext(ext: str, op: Op) -> str:
    """The file type after a step (a conversion changes it; most tools keep it; zipping gives a zip)."""
    if op.group == "convert" and op.id.startswith("to_"):
        return op.id[len("to_"):]
    return _FIXED_RESULT.get(op.id, ext)


def run_chain(paths, p):
    from convertanny_core.profiles import execute_chain
    sources=paths if isinstance(paths,(list,tuple)) else [paths]
    return execute_chain(sources,(p.get('_spec') or {}).get('steps') or [],
                         operations=lambda current,group: conversions(current) if group=='convert' else tools(current),
                         check=check_cancel,progress=report_progress)


def custom_op(spec: dict, group: str) -> Op:
    """Build the slice for a preset or chain the user made."""
    handlers = {"image": (image_preset, False), "video": (video_preset, False), "chain": (run_chain, True)}
    kind = spec.get("kind")
    if kind not in handlers:
        raise ConversionError("Unknown custom slice")
    handler, takes_many = handlers[kind]
    label = spec.get("name") or "Preset"
    return Op(id=f"custom:{spec.get('uid', label)}", label="★ " + label, fn=handler, group=group,
              multi=takes_many, hint=spec.get("hint", ""))


def run_op(op, paths, params=None, token=None):
    from convertanny_core.dispatch import run_operation
    return run_operation(op, paths, params, token)


def _cleanup(token):
    from convertanny_core.dispatch import cleanup_outputs
    cleanup_outputs(token)


_CATALOG_SAMPLES = ("a.png", "a.mp4", "a.mp3", "a.pdf", "a.md", "a.docx", "a.html", "a.txt", "a.pptx",
                    "a.xlsx", "a.csv", "a.srt", "a.vtt", "a.epub", "a.zip", "a.tar")


def count_catalog() -> tuple[int, int]:
    """Rough count of conversion pairs and tools, for the About box."""
    conversions_total = sum(len(conversions([name])) for name in _CATALOG_SAMPLES)
    tools_total = sum(len(tools([name])) for name in _CATALOG_SAMPLES)
    return conversions_total, tools_total
