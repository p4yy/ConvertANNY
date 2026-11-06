"""Isolated conversion jobs used by the desktop application.

The GUI owns this coordinator; conversion code runs in a spawned process so
long media and document operations never block Qt's event loop.
"""
from __future__ import annotations

import multiprocessing as mp
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable


_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
_CANCEL_GRACE_SECONDS = 0.8


def _run_in_worker(group, operation_id, paths, params, output_dir, events, cancel_event):
    """Resolve and run one catalog operation in a clean child interpreter."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetPriorityClass(
                ctypes.windll.kernel32.GetCurrentProcess(), 0x00004000
            )
        except (AttributeError, OSError):
            pass

    try:
        import engine

        engine.OUTPUT_DIR = output_dir
        token = engine.CancelToken()
        token.on_path = lambda kind, value: events.put((kind, value))

        def forward_cancellation():
            cancel_event.wait()
            token.cancel()

        threading.Thread(target=forward_cancellation, daemon=True).start()

        if operation_id.startswith("custom:"):
            operation = engine.custom_op(params.get("_spec") or {}, group)
        else:
            catalog = engine.conversions(paths) if group == "convert" else engine.tools(paths)
            operation = next((item for item in catalog if item.id == operation_id), None)
        if operation is None:
            events.put(("error", f"Unknown operation: {operation_id}"))
            return

        output_paths = engine.run_op(operation, paths, params, token=token)
        events.put(("done", [str(path) for path in output_paths if path]))
    except BaseException as error:
        try:
            import engine
            if isinstance(error, engine.Cancelled):
                events.put(("cancelled", None))
                return
        except Exception:
            pass
        events.put(("error", str(error) or error.__class__.__name__))


def terminate_process_tree(pid: int) -> None:
    """Stop a worker and any external tools it started."""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_NO_WINDOW,
            check=False,
        )
        return
    try:
        import psutil
        root = psutil.Process(pid)
        for child in root.children(recursive=True):
            try:
                child.kill()
            except psutil.Error:
                pass
        root.kill()
    except Exception:
        try:
            os.kill(pid, 9)
        except OSError:
            pass


def _remove_output(path: str) -> None:
    target = Path(path)
    for candidate in (target, target.with_name(target.name + ".part")):
        try:
            if candidate.is_dir():
                shutil.rmtree(candidate, ignore_errors=True)
            elif candidate.exists():
                candidate.unlink()
        except OSError:
            pass


class ConversionJob:
    """Parent-side worker lifecycle with progress, cancellation and cleanup."""

    def __init__(self, group, operation_id, paths, params, output_dir,
                 on_progress=None, on_count=None):
        self.args = (group, operation_id, list(paths), dict(params or {}), output_dir)
        self.on_progress = on_progress
        self.on_count = on_count
        self.failed: list[tuple[str, str]] = []
        self.outputs: list[str] = []
        self.temporary_directories: list[str] = []

    def run(self, should_cancel: Callable[[], bool]) -> tuple[str, object]:
        context = mp.get_context("spawn")
        events = context.Queue()
        cancel_event = context.Event()
        process = context.Process(
            target=_run_in_worker,
            args=(*self.args, events, cancel_event),
            daemon=True,
        )
        process.start()
        result = None
        cancellation_started = None

        try:
            while result is None:
                if cancellation_started is None and should_cancel():
                    cancel_event.set()
                    cancellation_started = time.monotonic()
                if (cancellation_started is not None
                        and time.monotonic() - cancellation_started > _CANCEL_GRACE_SECONDS):
                    terminate_process_tree(process.pid)
                    result = ("cancelled", None)
                    break

                try:
                    event, value = events.get(timeout=0.15)
                except queue.Empty:
                    if process.is_alive():
                        continue
                    result = self._drain_final_event(events)
                    if result is None:
                        result = (("cancelled", None) if cancellation_started is not None else
                                  ("error", f"The worker stopped unexpectedly (code {process.exitcode})"))
                    break

                self._record_event(event, value)
                if event in {"done", "error", "cancelled"}:
                    result = (event, value)
        finally:
            if process.is_alive():
                process.join(timeout=2)
            if process.is_alive():
                terminate_process_tree(process.pid)
                process.join(timeout=1)
            for directory in self.temporary_directories:
                shutil.rmtree(directory, ignore_errors=True)
            events.close()
            events.join_thread()

        if result[0] == "cancelled" or (result[0] == "done" and should_cancel()):
            for output in reversed(self.outputs):
                _remove_output(output)
            return ("cancelled", None)
        if result[0] == "error":
            for output in reversed(self.outputs):
                partial = Path(output).with_name(Path(output).name + ".part")
                if partial.exists():
                    _remove_output(output)
        return result

    def _drain_final_event(self, events):
        final = None
        while True:
            try:
                event, value = events.get_nowait()
            except queue.Empty:
                return final
            self._record_event(event, value)
            if event in {"done", "error", "cancelled"}:
                final = (event, value)

    def _record_event(self, event, value):
        if event == "progress" and self.on_progress:
            try:
                self.on_progress(float(value))
            except Exception:
                pass
        elif event == "count" and self.on_count:
            try:
                completed, total = value.split("/", 1)
                self.on_count(int(completed), int(total))
            except (ValueError, TypeError):
                pass
        elif event == "failed":
            try:
                import json
                self.failed.append(tuple(json.loads(value)))
            except (ValueError, TypeError):
                pass
        elif event == "out":
            self.outputs.append(value)
        elif event == "tmp":
            self.temporary_directories.append(value)
