"""Text encoding repair helpers for common Windows document imports."""
from __future__ import annotations

from pathlib import Path

from .model import ConversionError
from .paths import OutputPolicy, atomic_write


_ARABIC_RANGE = range(0x0600, 0x0700)
_MOJIBAKE_MARKERS = frozenset("ØÙÚÛ")


def _arabic_count(text: str) -> int:
    return sum(ord(character) in _ARABIC_RANGE for character in text)


def _recover_windows_bytes(text: str) -> bytes:
    recovered = bytearray()
    for character in text:
        try:
            recovered.extend(character.encode("cp1252"))
        except UnicodeEncodeError:
            codepoint = ord(character)
            if codepoint < 256:
                recovered.append(codepoint)
            else:
                recovered.extend(character.encode("utf-8"))
    return bytes(recovered)


def decode_arabic_text(raw: bytes) -> tuple[str, str]:
    """Return decoded text and repair label; leave correct UTF-8 untouched."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return raw.decode("cp1256"), "windows-1256"
        except UnicodeDecodeError as exc:
            raise ConversionError("The file is not valid UTF-8 or Windows-1256 text") from exc

    suspicious = sum(character in _MOJIBAKE_MARKERS for character in text)
    if suspicious >= 3 and _arabic_count(text) == 0:
        try:
            repaired = _recover_windows_bytes(text).decode("utf-8")
        except UnicodeDecodeError:
            return text, ""
        if _arabic_count(repaired) >= 2:
            return repaired, "mojibake"
    return text, ""


def repair_arabic_file(source: str | Path, *, policy: OutputPolicy | None = None) -> Path:
    source = Path(source)
    if not source.is_file():
        raise ConversionError(f"File not found: {source}")
    text, repair = decode_arabic_text(source.read_bytes())
    if not repair:
        raise ConversionError("This file already contains valid UTF-8 text")
    extension = source.suffix.lstrip(".") or "txt"
    destination = (policy or OutputPolicy(suffix=" fixed")).destination(source, extension)
    encoding = "utf-8-sig" if source.suffix.casefold() in {".csv", ".txt", ".tsv"} else "utf-8"
    return atomic_write(destination, lambda temporary: temporary.write_text(text, encoding=encoding, newline=""))
