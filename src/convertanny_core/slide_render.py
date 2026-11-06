"""Presentation conversion routes for slide image export."""

from __future__ import annotations

from pathlib import Path
from typing import Callable


def slide_image_converter(fmt: str, *, native_enabled: bool, native_export: Callable,
                          document_export: Callable, rasterizer: Callable,
                          output_directory: Callable, output_file: Callable):
    """Build a slide converter preferring native export and falling back through PDF."""
    def convert(source, params):
        source = Path(source).resolve()
        if native_enabled:
            result = native_export(source, fmt)
            if result:
                return result

        intermediate = document_export(source, "pdf")
        try:
            rendered = rasterizer(fmt, dpi=150)(intermediate, params)
            if rendered.is_dir():
                destination = output_directory(source, fmt.upper())
            else:
                destination = output_file(source, fmt)
            rendered.rename(destination)
            return destination
        finally:
            Path(intermediate).unlink(missing_ok=True)

    return convert
