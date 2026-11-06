"""Build PDF image pages with explicit physical sizing and lossless image embedding."""
from __future__ import annotations

import io


def image_page_bytes(image, *, dpi: float = 150) -> bytes:
    """Encode one raster image as a one-page PDF at the requested print resolution."""
    import pymupdf

    if dpi <= 0:
        raise ValueError("dpi must be positive")
    width, height = image.size
    if width < 1 or height < 1:
        raise ValueError("image must have non-zero dimensions")
    png = io.BytesIO()
    image.save(png, format="PNG")
    scale = 72.0 / dpi
    document = pymupdf.open()
    try:
        page = document.new_page(width=width * scale, height=height * scale)
        page.insert_image(page.rect, stream=png.getvalue(), keep_proportion=False)
        return document.tobytes(deflate=True)
    finally:
        document.close()
