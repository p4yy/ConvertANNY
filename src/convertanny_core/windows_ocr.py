"""Run local Windows text recognition and save its result beside the source."""

from __future__ import annotations

import subprocess
import tempfile
from contextlib import ExitStack
from pathlib import Path
from typing import Callable

from .model import ConversionError
from .paths import atomic_write


def recognize_image_text(source: str | Path, destination: str | Path, *, windows: bool,
                         open_image: Callable, flatten: Callable, image_module: Callable,
                         script_text: str, creation_flags: int,
                         run: Callable = subprocess.run) -> Path:
    """Recognize text in an image with the installed Windows OCR languages."""
    if not windows:
        raise ConversionError("Copying text from images needs Windows 10 or 11")

    source, destination = Path(source), Path(destination)
    image, _ = image_module()
    with tempfile.TemporaryDirectory(prefix="convertanny-ocr-") as workspace:
        workspace = Path(workspace)
        image_file = workspace / "input.png"
        script_file = workspace / "recognize.ps1"
        with ExitStack() as images:
            original = open_image(source)
            images.callback(original.close)
            page = flatten(original)
            if page is not original:
                images.callback(page.close)
            if max(page.size) > 9000:
                page.thumbnail((9000, 9000), image.LANCZOS)
            page.save(str(image_file), format="PNG")
        script_file.write_text(script_text, encoding="utf-8-sig")
        command = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                   "-File", str(script_file), "-Path", str(image_file)]
        result = run(command, capture_output=True, timeout=120, stdin=subprocess.DEVNULL,
                     creationflags=creation_flags)

    text = result.stdout.decode("utf-8", "replace").strip()
    if not text:
        if result.returncode != 0:
            raise ConversionError("Windows text recognition isn't available on this PC")
        raise ConversionError("No text found in this image")

    return atomic_write(destination, lambda temporary: temporary.write_text(text + "\n", encoding="utf-8"))
