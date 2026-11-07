"""Small image building blocks shared by the engine: opening, flattening, format preparation, stitching, GIF frames.

Everything takes and returns Pillow images, so it can be tested with generated pictures.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageOps

_OPAQUE_FIRST = ("jpg", "bmp", "pdf", "jp2")          # formats with no alpha channel
_NATIVE_MODES = ("RGB", "RGBA", "L", "LA")
_ICON_FORMATS = ("ico", "icns")
_ICNS_LIMIT = 1024
_SVG_DPI = 192
GIF_LONG_SIDE = 1200
GIF_SECONDS = (0.02, 30.0)


def enable_heif() -> None:
    """Let Pillow read HEIC/HEIF when pillow-heif is installed (optional)."""
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except Exception:
        pass


def load(path, is_svg: bool) -> Image.Image:
    """Open an image upright. SVGs are rasterised with an alpha channel."""
    if is_svg:
        import pymupdf
        with pymupdf.open(str(path)) as document:
            png = document[0].get_pixmap(dpi=_SVG_DPI, alpha=True).tobytes("png")
        picture = Image.open(io.BytesIO(png))
        picture.load()
        return picture
    picture = Image.open(str(path))
    try:
        return ImageOps.exif_transpose(picture)
    except Exception:
        return picture


def has_transparency(picture: Image.Image) -> bool:
    return picture.mode in ("RGBA", "LA") or (picture.mode == "P" and "transparency" in picture.info)


def flatten(picture: Image.Image, background=(255, 255, 255)) -> Image.Image:
    """An opaque RGB copy; see-through areas take the background colour."""
    if not has_transparency(picture):
        return picture.convert("RGB")
    layered = picture.convert("RGBA")
    base = Image.new("RGB", layered.size, background)
    base.paste(layered, mask=layered.getchannel("A"))
    return base


def square_canvas(picture: Image.Image) -> Image.Image:
    """The picture centred on a transparent square as wide as its longer side (icons are square)."""
    side = max(picture.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(picture.convert("RGBA"), ((side - picture.width) // 2, (side - picture.height) // 2))
    return canvas


def prepare_for_format(picture: Image.Image, fmt: str) -> Image.Image:
    """Convert to a mode the target format can store."""
    if fmt in _OPAQUE_FIRST or (fmt == "heic" and picture.mode not in ("RGB", "RGBA")):
        picture = flatten(picture)
    elif fmt == "gif":
        if picture.mode not in ("P", "L"):
            picture = picture.convert("RGBA")
    elif picture.mode not in _NATIVE_MODES:
        picture = picture.convert("RGBA")
    if fmt in _ICON_FORMATS:
        picture = square_canvas(picture)
        if fmt == "icns" and picture.width > _ICNS_LIMIT:
            picture = picture.resize((_ICNS_LIMIT, _ICNS_LIMIT), Image.LANCZOS)
    return picture


def stitch(pictures: Sequence[Image.Image], horizontal: bool) -> Image.Image:
    """Join pictures in a row (equal heights) or column (equal widths), scaling to the smallest."""
    layers = [p.convert("RGBA") for p in pictures]
    axis = 1 if horizontal else 0           # size[1] is the height, size[0] the width
    target = min(p.size[axis] for p in layers)
    scaled = []
    for p in layers:
        along = 0 if horizontal else 1
        scaled_length = max(1, round(p.size[along] * target / p.size[axis]))
        scaled.append(p.resize((scaled_length, target) if horizontal else (target, scaled_length), Image.LANCZOS))
    total = sum(p.size[0 if horizontal else 1] for p in scaled)
    canvas = Image.new("RGBA", (total, target) if horizontal else (target, total), (0, 0, 0, 0))
    offset = 0
    for p in scaled:
        canvas.paste(p, (offset, 0) if horizontal else (0, offset))
        offset += p.size[0 if horizontal else 1]
    return canvas


def any_transparent(pictures: Sequence[Image.Image]) -> bool:
    """True when some picture has a pixel that is not fully opaque (expects RGBA)."""
    return any(p.getextrema()[3][0] < 255 for p in pictures)


def gif_box(first_size: tuple[int, int]) -> tuple[int, int]:
    """Frame size for an animation: the first picture's size, shrunk so its longer side is at most 1200."""
    longest = max(first_size)
    if longest <= GIF_LONG_SIDE:
        return first_size
    ratio = GIF_LONG_SIDE / longest
    return round(first_size[0] * ratio), round(first_size[1] * ratio)


def gif_frame(picture: Image.Image, box: tuple[int, int]) -> Image.Image:
    """The picture fitted inside `box` and centred on white."""
    fitted = flatten(picture)
    fitted.thumbnail(box, Image.LANCZOS)
    frame = Image.new("RGB", box, (255, 255, 255))
    frame.paste(fitted, ((box[0] - fitted.width) // 2, (box[1] - fitted.height) // 2))
    return frame


def clamp_seconds(value: float) -> float:
    low, high = GIF_SECONDS
    return min(high, max(low, value))
