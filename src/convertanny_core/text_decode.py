"""Read human-authored documents while preserving their original Unicode text."""
from __future__ import annotations

from pathlib import Path


_UNICODE_DECODERS = ("utf-8-sig",)


def _arabic_density(text: str) -> int:
    """Count Arabic-script letters to distinguish Windows Arabic from Western code pages."""
    return sum("\u0600" <= char <= "\u06ff" or "\u0750" <= char <= "\u077f"
               or "\u08a0" <= char <= "\u08ff" for char in text)


def _western_density(text: str) -> int:
    return sum(char.isascii() and char.isalpha() or "\u00c0" <= char <= "\u024f" for char in text)


def decode_document(data: bytes) -> str:
    """Decode text in a predictable order, including Arabic Windows exports and BOM files."""
    for codec in _UNICODE_DECODERS:
        try:
            return data.decode(codec)
        except UnicodeDecodeError:
            continue
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    western = arabic = None
    for codec in ("cp1252", "cp1256"):
        try:
            candidate = data.decode(codec)
        except UnicodeDecodeError:
            continue
        if codec == "cp1252":
            western = candidate
        else:
            arabic = candidate
    if arabic is not None and _arabic_density(arabic) >= _western_density(western or "") and _arabic_density(arabic):
        return arabic
    if western is not None:
        return western
    if arabic is not None:
        return arabic
    return data.decode("latin-1")


def read_document(path: str | Path) -> str:
    """Load a text document from disk and decode it using ConvertANNY's encoding policy."""
    return decode_document(Path(path).read_bytes())
