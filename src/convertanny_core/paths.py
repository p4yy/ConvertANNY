"""Non-destructive output naming and atomic file replacement."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from uuid import uuid4

from .model import CancelToken, ConversionError


@dataclass(frozen=True)
class OutputPolicy:
    """Choose an output location without replacing user data."""

    directory: Path | None = None
    suffix: str = ""

    def destination(self, source: str | Path, extension: str) -> Path:
        source = Path(source)
        extension = extension.lower().lstrip(".")
        if not extension or any(c in extension for c in "\\/:*?\"<>|"):
            raise ConversionError("Invalid output format")
        parent = self.directory or source.parent
        parent = Path(parent)
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except PermissionError as exc:
            raise ConversionError(
                f"ConvertANNY cannot write to {parent}. Choose another output folder in Preferences → Files & jobs."
            ) from exc
        stem = source.stem + self.suffix
        candidate = parent / f"{stem}.{extension}"
        ordinal = 2
        while candidate.exists():
            candidate = parent / f"{stem} ({ordinal}).{extension}"
            ordinal += 1
        return candidate


def atomic_write(destination: Path, writer: Callable[[Path], None], token: CancelToken | None = None) -> Path:
    """Write to a sibling temporary file and publish it only when complete."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.stem}.{uuid4().hex}.part")
    reservation = uuid4().hex.encode("ascii")
    reserved = False
    try:
        if token:
            token.check()
        writer(temporary)
        if token:
            token.check()
        if not temporary.is_file():
            raise ConversionError("The conversion did not create an output file")
        # Reserve the destination atomically so an unrelated file can never be replaced.
        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        reserved = True
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(reservation)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        reserved = False
        return destination
    except FileExistsError as exc:
        raise ConversionError(f"Output already exists: {destination.name}") from exc
    except Exception as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        if reserved:
            try:
                if destination.read_bytes() == reservation:
                    destination.unlink()
            except OSError:
                pass
        if isinstance(exc, PermissionError):
            raise ConversionError(
                f"ConvertANNY couldn't save {destination.name}. The destination may be read-only or in use. "
                "Close the file, or choose another output folder in Preferences → Files & jobs."
            ) from exc
        raise
