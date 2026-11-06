"""Lossless file splitting and joining with collision-safe output publishing."""
from __future__ import annotations

import re
from pathlib import Path

from .model import CancelToken, ConversionError
from .paths import OutputPolicy, atomic_write


def is_part_file(path) -> bool:
    return bool(re.search(r"\.[0-9]{3,}$", Path(path).name))


def split_file(source, part_bytes: int, *, directory=None, token: CancelToken | None = None) -> list[Path]:
    source = Path(source)
    if not source.is_file():
        raise ConversionError("Choose a file to split")
    part_bytes = int(part_bytes)
    total = source.stat().st_size
    if part_bytes <= 0:
        raise ConversionError("Part size must be positive")
    if total <= part_bytes:
        raise ConversionError("This is already smaller than one part")
    folder = Path(directory) if directory else source.parent
    folder.mkdir(parents=True, exist_ok=True)
    count = (total + part_bytes - 1) // part_bytes
    name = source.name
    ordinal = 2
    while any((folder / f"{name}.{number:03d}").exists() for number in range(1,count+1)):
        name = f"{source.stem} ({ordinal}){source.suffix}"
        ordinal += 1
    completed = []
    processed = 0
    try:
        with source.open("rb") as incoming:
            for number in range(1,count+1):
                remaining = min(part_bytes,total-processed)
                destination = folder / f"{name}.{number:03d}"
                def write(temporary):
                    nonlocal processed
                    left = remaining
                    with temporary.open("wb") as outgoing:
                        while left:
                            if token:
                                token.check()
                            block = incoming.read(min(left,1024*1024))
                            if not block:
                                raise ConversionError("The source file changed while splitting")
                            outgoing.write(block)
                            left -= len(block)
                            processed += len(block)
                            if token:
                                token.report(processed/total)
                completed.append(atomic_write(destination,write,token))
        return completed
    except BaseException:
        for path in completed:
            path.unlink(missing_ok=True)
        raise


def join_files(selected, *, directory=None, token: CancelToken | None = None) -> Path:
    selected = Path(selected)
    match = re.fullmatch(r"(.+)\.([0-9]{3,})",selected.name)
    if match is None:
        raise ConversionError("Choose a numbered file part, such as .001")
    base = match.group(1)
    numbered = {}
    pattern = re.compile(re.escape(base)+r"\.([0-9]{3,})")
    for candidate in selected.parent.iterdir():
        found = pattern.fullmatch(candidate.name)
        if found and candidate.is_file():
            number = int(found.group(1))
            if number in numbered:
                raise ConversionError("Duplicate numbered parts were found")
            numbered[number] = candidate
    if not numbered or sorted(numbered) != list(range(1,max(numbered)+1)):
        raise ConversionError("Some parts are missing")
    parts = [numbered[number] for number in sorted(numbered)]
    total = sum(part.stat().st_size for part in parts)
    original = selected.with_name(base)
    destination = None
    if original.suffix:
        policy = OutputPolicy(directory=Path(directory) if directory else None)
        destination = policy.destination(original,original.suffix.lstrip("."))
    if destination is None:
        parent = Path(directory) if directory else selected.parent
        destination = parent/base
        number=2
        while destination.exists():
            destination = parent/f"{base} ({number})"
            number+=1
    def write(temporary):
        processed=0
        with temporary.open("wb") as outgoing:
            for part in parts:
                with part.open("rb") as incoming:
                    while True:
                        if token:
                            token.check()
                        chunk=incoming.read(1024*1024)
                        if not chunk:
                            break
                        outgoing.write(chunk)
                        processed+=len(chunk)
                        if token:
                            token.report(processed/max(1,total))
        if processed != total:
            raise ConversionError("The numbered files changed while joining")
    return atomic_write(destination,write,token)
