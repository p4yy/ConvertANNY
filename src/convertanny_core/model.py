"""Small, stable types shared by ConvertANNY's own engine modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Lock
from typing import Callable


class ConversionError(RuntimeError):
    """An input or operation could not be converted safely."""


class Cancelled(ConversionError):
    """The user cancelled an operation."""


class CancelToken:
    """Cooperative cancellation and monotonic progress reporting."""

    def __init__(self, on_progress: Callable[[float], None] | None = None):
        self._event = Event()
        self._lock = Lock()
        self._progress = 0.0
        self._on_progress = on_progress

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def check(self) -> None:
        if self.cancelled:
            raise Cancelled("Conversion cancelled")

    def report(self, value: float) -> None:
        value = max(0.0, min(1.0, float(value)))
        with self._lock:
            self._progress = max(self._progress, value)
            current = self._progress
        if self._on_progress:
            self._on_progress(current)


@dataclass(frozen=True)
class Operation:
    """A typed ConvertANNY operation; IDs remain stable across UI surfaces."""

    id: str
    title: str
    category: str
    source_extensions: tuple[str, ...] = ()
    target_extension: str | None = None
    accepts_multiple: bool = False
    description: str = ""
    parameters: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def accepts(self, path: str | Path) -> bool:
        if not self.source_extensions:
            return True
        return Path(path).suffix.lower().lstrip(".") in self.source_extensions
