"""Privacy-aware formatting for local ConvertANNY diagnostic reports."""
from __future__ import annotations

from pathlib import Path


def anonymize_report(text: str, *, home: str = "", username: str = "") -> str:
    """Replace known account identifiers in report text before it is shown or saved."""
    for location in {home, home.replace("\\", "/")}:
        if location:
            text = text.replace(location, "%USERPROFILE%")
    if len(username) > 2:
        text = text.replace(username, "<user>")
    return text


def compose_report(*, app_version: str, installed: bool, os_version: str, python_version: str,
                   qt_version: str, language: str, kind: str, details: str,
                   log_lines=(), home: str = "", username: str = "") -> str:
    """Format diagnostic context as a plain-text report, then scrub local account details."""
    mode = "installed" if installed else "source"
    lines = [f"ConvertANNY {app_version} ({mode})",
             f"Windows {os_version} · Python {python_version} · Qt {qt_version}",
             f"Language: {language}", "", f"What happened: {kind}", "", details.strip()]
    tail = list(log_lines)[-25:]
    if tail:
        lines += ["", "Last log lines:"] + tail
    return anonymize_report("\n".join(lines), home=home, username=username)
