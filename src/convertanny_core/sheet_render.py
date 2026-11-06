"""Spreadsheet rendering pipeline with native office export and HTML fallback."""

from __future__ import annotations

from pathlib import Path
from typing import Callable


def spreadsheet_to_pdf(source, *, native_available: Callable[[], bool], native_export: Callable,
                       html_export: Callable, html_content: Callable, html_render: Callable, output: Path,
                       native_error: type[Exception]) -> Path:
    """Prefer a spreadsheet application's PDF export, then render a temporary HTML view."""
    source = Path(source)
    if native_available():
        try:
            return native_export(source, "pdf")
        except native_error:
            pass

    intermediate = Path(html_export(source, None))
    try:
        return html_render(html_content(intermediate), output)
    finally:
        intermediate.unlink(missing_ok=True)
