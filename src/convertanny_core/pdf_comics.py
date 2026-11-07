"""PDF page rasterization for ConvertANNY comic archives."""

from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path
from typing import Callable

from .model import CancelToken
from .paths import atomic_write


def pdf_to_cbz(source: str | Path, output: str | Path, *, open_document: Callable,
               token: CancelToken | None = None) -> Path:
    """Rasterize a PDF at 150 DPI and store its JPEG pages in reading order."""
    source, output = Path(source), Path(output)
    with tempfile.TemporaryDirectory(prefix="convertanny-comic-") as workspace:
        pages_dir = Path(workspace)
        document = open_document(str(source))
        try:
            page_paths = []
            for index, page in enumerate(document, start=1):
                if token:
                    token.check()
                page_path = pages_dir / f"{index:04d}.jpg"
                page.get_pixmap(dpi=150).save(str(page_path), jpg_quality=90)
                page_paths.append(page_path)
        finally:
            document.close()

        width = max(3, len(str(len(page_paths))))

        def write_archive(temporary: Path) -> None:
            with zipfile.ZipFile(temporary, "w", zipfile.ZIP_STORED) as archive:
                for index, page_path in enumerate(page_paths, start=1):
                    if token:
                        token.check()
                    archive.write(page_path, f"{index:0{width}d}.jpg")

        return atomic_write(output, write_archive, token)
