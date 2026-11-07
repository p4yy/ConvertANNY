"""ConvertANNY external-tool execution with bounded diagnostics and reliable cancellation.

This module owns process and pipe lifetimes. Callers provide an argument vector,
never a shell command. The desktop adapter can pass its existing cancellation
and progress callbacks without importing any GUI framework.
"""
from __future__ import annotations

import math
import os
import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Callable, Sequence

from .model import Cancelled


_ERROR_BYTES = 16 * 1024
_POLL_SECONDS = 0.08
_WINDOWS_NO_CONSOLE = 0x08000000
_WINDOWS_DETACHED = 0x00000008
_WINDOWS_LOW_PRIORITY = 0x00004000


class DesktopCancelToken:
    """Cancellation state shared by an operation and all external tools it owns.

    Paths, on_path and batch remain part of the desktop event contract.
    Process registration is synchronized so cancellation cannot miss a process
    launched at the same instant.
    """

    def __init__(self) -> None:
        self._cancel = threading.Event()
        self._lock = threading.RLock()
        self.procs: list[subprocess.Popen] = []
        self.paths: list[Path] = []
        self.on_path: Callable[[str, str], None] | None = None
        self.batch: tuple[int, int] = (0, 1)

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def cancel(self) -> None:
        with self._lock:
            self._cancel.set()
            running = tuple(self.procs)
        for process in running:
            _stop_process(process)

    def _track(self, process: subprocess.Popen) -> None:
        with self._lock:
            self.procs.append(process)
            already_cancelled = self._cancel.is_set()
        if already_cancelled:
            _stop_process(process)
            raise Cancelled("Conversion cancelled")

    def _release(self, process: subprocess.Popen) -> None:
        with self._lock:
            if process in self.procs:
                self.procs.remove(process)


def _stop_process(process: subprocess.Popen) -> None:
    try:
        if process.poll() is None:
            process.kill()
    except (OSError, ValueError):
        pass


class _DiagnosticTail:
    """Retain a fixed-size suffix even if a backend emits gigabytes to stderr."""

    def __init__(self, limit: int = _ERROR_BYTES) -> None:
        self._limit = limit
        self._parts: deque[bytes] = deque()
        self._size = 0

    def append(self, data: bytes) -> None:
        if len(data) >= self._limit:
            self._parts.clear()
            data = data[-self._limit:]
            self._size = 0
        self._parts.append(data)
        self._size += len(data)
        while self._size > self._limit:
            removed = self._parts.popleft()
            self._size -= len(removed)
        # Partial trimming avoids throwing away a short, useful error message.
        if self._size < self._limit and self._parts and self._parts[0] == b"":
            self._parts.popleft()

    def summary(self) -> str:
        last_lines = b"".join(self._parts).decode("utf-8", "replace").splitlines()[-4:]
        return "\n".join(item for item in last_lines if item.strip()).strip()


def _validate_argv(command: Sequence[str | os.PathLike[str]]) -> list[str]:
    if isinstance(command, (str, bytes)) or not command:
        raise ValueError("An external tool needs a nonempty argument vector")
    argv = [os.fspath(arg) for arg in command]
    if any(not isinstance(arg, str) or not arg or "\x00" in arg for arg in argv):
        raise ValueError("External-tool arguments must be nonempty strings without NUL")
    return argv


def _progress_from_line(line: bytes, duration: float, span: tuple[float, float]) -> float | None:
    key, separator, raw = line.partition(b"=")
    if not separator or key.strip() not in (b"out_time_us", b"out_time_ms"):
        return None
    try:
        measured_us = int(raw.strip())
    except ValueError:
        return None
    value = measured_us / (duration * 1_000_000)
    if not math.isfinite(value):
        return None
    normalized = max(0.0, min(1.0, value))
    return span[0] + normalized * (span[1] - span[0])


def run_tool(
    command: Sequence[str | os.PathLike[str]], *,
    cwd: str | os.PathLike[str] | None = None,
    accepted: tuple[int, ...] = (0,),
    duration: float = 0.0,
    span: tuple[float, float] = (0.0, 1.0),
    detached: bool = False,
    token: DesktopCancelToken | None = None,
    check: Callable[[], None] = lambda: None,
    progress: Callable[[float], None] = lambda _value: None,
    error_type: type[Exception] = RuntimeError,
    on_stderr: Callable[[str], None] | None = None,
) -> None:
    """Run one tool, forwarding progress and up to 16 KiB of diagnostic context.

    Pipes are drained independently to prevent deadlocks. Cancellation and
    failures always reap the child. Accepted describes successful exit
    codes; a non-zero error includes the last four stderr lines.
    """
    argv = _validate_argv(command)
    if not math.isfinite(duration) or duration < 0:
        raise ValueError("Media duration must be finite and nonnegative")
    if len(span) != 2 or not all(math.isfinite(n) for n in span):
        raise ValueError("Progress span must contain two finite values")
    check()
    if token and token.cancelled:
        raise Cancelled("Conversion cancelled")

    flags = 0
    if os.name == "nt":
        flags = _WINDOWS_LOW_PRIORITY | (_WINDOWS_DETACHED if detached else _WINDOWS_NO_CONSOLE)

    process = subprocess.Popen(
        argv, cwd=cwd, shell=False, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE if duration > 0 else subprocess.DEVNULL,
        stderr=subprocess.PIPE, creationflags=flags,
    )
    diagnostic = _DiagnosticTail()
    last_progress = -math.inf

    def read_stderr() -> None:
        assert process.stderr is not None
        while packet := process.stderr.readline(4096):
            diagnostic.append(packet)
            if on_stderr:
                try:
                    on_stderr(packet.decode("utf-8", "replace").rstrip("\r\n"))
                except Exception:
                    pass

    def read_progress() -> None:
        nonlocal last_progress
        assert process.stdout is not None
        while packet := process.stdout.readline(2048):
            value = _progress_from_line(packet, duration, span)
            if value is None or value < last_progress + 0.005:
                continue
            last_progress = value
            try:
                progress(value)
            except Exception:
                pass

    stderr_thread = threading.Thread(target=read_stderr, name="ConvertANNY-stderr", daemon=True)
    progress_thread = (
        threading.Thread(target=read_progress, name="ConvertANNY-progress", daemon=True)
        if duration > 0 else None
    )
    try:
        if token:
            token._track(process)
        stderr_thread.start()
        if progress_thread:
            progress_thread.start()
        while process.poll() is None:
            check()
            if token and token.cancelled:
                raise Cancelled("Conversion cancelled")
            try:
                process.wait(timeout=_POLL_SECONDS)
            except subprocess.TimeoutExpired:
                continue
        check()
        if token and token.cancelled:
            raise Cancelled("Conversion cancelled")
        stderr_thread.join()
        if progress_thread:
            progress_thread.join()
        if process.returncode not in accepted:
            message = diagnostic.summary() or f"{Path(argv[0]).name} failed (exit {process.returncode})"
            raise error_type(message)
    finally:
        _stop_process(process)
        process.wait()
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
        if stderr_thread.ident is not None:
            stderr_thread.join(timeout=2)
        if progress_thread and progress_thread.ident is not None:
            progress_thread.join(timeout=2)
        if token:
            token._release(process)
