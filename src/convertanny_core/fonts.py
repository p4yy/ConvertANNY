"""ConvertANNY font format conversion and per-user installation."""

from __future__ import annotations

import ctypes
import json
import os
import sys
from pathlib import Path

from .model import CancelToken, ConversionError
from .paths import OutputPolicy, atomic_write


def _font_kind(font) -> str:
    return "otf" if "CFF " in font or "CFF2" in font else "ttf"


def _quadratic_outlines(font, tolerance: float = 1.0, reverse_direction: bool = True) -> None:
    """Convert PostScript outlines to quadratic TrueType outlines."""
    from fontTools.pens.cu2quPen import Cu2QuPen
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.ttLib import newTable

    names = font.getGlyphOrder()
    glyph_set = font.getGlyphSet()
    glyf = newTable("glyf")
    glyf.glyphOrder = names
    glyf.glyphs = {}
    for name in names:
        pen = TTGlyphPen(glyph_set)
        glyph_set[name].draw(Cu2QuPen(pen, tolerance, reverse_direction=reverse_direction))
        glyf[name] = pen.glyph()

    font["loca"] = newTable("loca")
    font["glyf"] = glyf
    for table in ("CFF ", "CFF2", "VORG"):
        if table in font:
            del font[table]
    font["maxp"] = newTable("maxp")
    font["maxp"].tableVersion = 0x00010000
    for field in ("maxZones", "maxTwilightPoints", "maxStorage", "maxFunctionDefs",
                  "maxInstructionDefs", "maxStackElements", "maxSizeOfInstructions",
                  "maxComponentElements"):
        setattr(font["maxp"], field, 0)
    font["maxp"].maxZones = 1
    font["head"].glyphDataFormat = 0
    font["post"].formatType = 2.0
    font["post"].extraNames = []
    font["post"].mapping = {}
    font["post"].glyphOrder = names
    font.sfntVersion = "\x00\x01\x00\x00"


def convert_font(source: str | Path, target_format: str, *, directory: str | Path | None = None,
                 token: CancelToken | None = None) -> Path:
    from fontTools.ttLib import TTFont

    source = Path(source)
    target_format = target_format.lower().lstrip(".")
    if target_format not in {"ttf", "otf", "woff", "woff2"}:
        raise ConversionError(f"Unsupported font format: {target_format}")
    if token:
        token.check()
    try:
        font = TTFont(str(source))
    except Exception as error:
        raise ConversionError(f"Could not read this font: {error}") from error

    source_kind = _font_kind(font)
    if target_format in {"woff", "woff2"}:
        font.flavor = target_format
        output_format = target_format
    elif target_format == "otf" and source_kind == "ttf":
        # A quadratic TrueType outline cannot become a CFF OpenType outline by
        # changing its extension. Keep its real container format.
        font.flavor = None
        output_format = "ttf"
    elif target_format == "ttf" and source_kind == "otf":
        try:
            _quadratic_outlines(font)
        except Exception as error:
            raise ConversionError(f"Could not convert these outlines to TrueType: {error}") from error
        font.flavor = None
        output_format = "ttf"
    else:
        font.flavor = None
        output_format = target_format

    policy = OutputPolicy(directory=Path(directory) if directory else source.parent)
    destination = policy.destination(source, output_format)

    def write(temporary: Path):
        if token:
            token.check()
        font.save(str(temporary))

    try:
        return atomic_write(destination, write, token)
    finally:
        font.close()


def install_font(source: str | Path, *, token: CancelToken | None = None,
                 local_app_data: str | Path | None = None) -> str:
    from fontTools.ttLib import TTFont

    if sys.platform != "win32":
        raise ConversionError("Installing fonts is available on Windows")
    source = Path(source)
    if token:
        token.check()
    try:
        font = TTFont(str(source))
    except Exception as error:
        raise ConversionError(f"Could not read this font: {error}") from error

    family = font["name"].getDebugName(4) or source.stem
    font.flavor = None
    extension = _font_kind(font)
    base = Path(local_app_data) if local_app_data else Path(
        os.environ.get("LOCALAPPDATA", str(Path.home()))
    )
    folder = base / "Microsoft" / "Windows" / "Fonts"
    destination = OutputPolicy(directory=folder).destination(source, extension)

    def write(temporary: Path):
        if token:
            token.check()
        font.save(str(temporary))

    try:
        installed = atomic_write(destination, write, token)
    except Exception:
        font.close()
        raise
    font.close()

    try:
        import winreg
        entry = f"{family} ({'TrueType' if extension == 'ttf' else 'OpenType'})"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              r"Software\Microsoft\Windows NT\CurrentVersion\Fonts") as key:
            winreg.SetValueEx(key, entry, 0, winreg.REG_SZ, str(installed))
        ctypes.windll.gdi32.AddFontResourceW(str(installed))
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001D, 0, 0, 0x0002, 1000, None)
    except Exception as error:
        installed.unlink(missing_ok=True)
        raise ConversionError(f"Windows could not register this font: {error}") from error
    return "info:" + json.dumps({"font": family}, ensure_ascii=False)
