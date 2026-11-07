"""Portable contract and failure-injection tests for the external-tool runner."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from convertanny_core.model import Cancelled
from convertanny_core.processes import DesktopCancelToken, _DiagnosticTail, run_tool


def invoke(script: str, **kwargs) -> None:
    run_tool([sys.executable, "-u", "-c", script], **kwargs)


def test_success_and_accepted_exit_codes():
    invoke("print('hello')")
    invoke("raise SystemExit(3)", accepted=(0, 3))


def test_error_and_last_four_lines():
    with pytest.raises(RuntimeError) as error:
        invoke("import sys; [print('err' + str(i), file=sys.stderr) for i in range(12)]; sys.exit(4)")
    assert str(error.value).splitlines() == [f"err{i}" for i in range(8, 12)]


def test_large_streams_do_not_deadlock_or_exhaust_memory():
    errors = []
    invoke("import sys; sys.stderr.write('x'*2000000); sys.stdout.write('out_time_us=1000000\n')",
           duration=1.0, progress=errors.append)
    assert errors == [1.0]


def test_stderr_callback_and_faults():
    captured = []
    invoke("import sys; print('A', file=sys.stderr); print('B', file=sys.stderr)",
           on_stderr=captured.append)
    assert captured == ["A", "B"]
    invoke("import sys; print('hi', file=sys.stderr)", on_stderr=lambda _: 1 / 0)


def test_progress_ignores_invalid_records_and_regressions():
    values = []
    invoke("print('garbage'); print('out_time_us=500000'); print('out_time_ms=100000'); "
           "print('out_time_ms=1000000'); print('out_time_us=99999999999999')",
           duration=1.0, span=(0.2, 0.8), progress=values.append)
    assert values == pytest.approx([0.5, 0.8])


def test_cancel_during_running_process_reaps_child():
    token = DesktopCancelToken()
    started = threading.Event()
    outcome = []

    def run():
        try:
            invoke("import time; time.sleep(30)", token=token, check=lambda: started.set())
        except Cancelled:
            outcome.append("cancelled")

    thread = threading.Thread(target=run)
    thread.start()
    assert started.wait(timeout=5)
    time.sleep(0.15)
    token.cancel()
    thread.join(timeout=4)
    assert not thread.is_alive()
    assert outcome == ["cancelled"]
    assert token.procs == []


def test_cancelled_before_spawn():
    token = DesktopCancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        invoke("print('should never run')", token=token)
    assert token.procs == []


def test_cancel_from_check_and_cleanup():
    def fail():
        raise ValueError("cancel requested")

    with pytest.raises(ValueError, match="cancel requested"):
        invoke("import time; time.sleep(30)", check=fail)


def test_bad_commands_and_duration():
    for command in ("echo hi", [], ["bad\x00argument"]):
        with pytest.raises(ValueError):
            run_tool(command)
    with pytest.raises(ValueError):
        invoke("pass", duration=float("nan"))
    with pytest.raises(ValueError):
        invoke("pass", span=(float("inf"), 1.0))


def test_diagnostic_tail_is_bounded():
    tail = _DiagnosticTail(100)
    for _ in range(1000):
        tail.append(b"abcdef\n")
    assert len(tail.summary().encode()) <= 100


def test_progress_and_error_paths_release_token():
    token = DesktopCancelToken()
    with pytest.raises(RuntimeError):
        invoke("raise SystemExit(13)", token=token)
    assert not token.procs
