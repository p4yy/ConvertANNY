"""Characterize image-page conversion for PDF layout and rendered pixels."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import engine
import pymupdf
from PIL import Image


def check_page_box_pixels_and_alpha_flattening():
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "sample.png"
        image = Image.new("RGBA", (60, 30), (245, 50, 15, 255))
        image.putpixel((0, 0), (0, 0, 255, 0))
        image.save(path)
        document = engine._image_pdf_page(path)
        try:
            page = document[0]
            assert document.page_count == 1
            assert round(page.rect.width, 3) == 28.8 and round(page.rect.height, 3) == 14.4
            pixmap = page.get_pixmap(dpi=150, alpha=False)
            assert (pixmap.width, pixmap.height) == (60, 30)
            rendered = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            corner = rendered.getpixel((0, 0))
            centre = rendered.getpixel((30, 15))
            assert corner[0] > 230 and corner[1] > 140 and corner[2] > 120, corner
            assert max(abs(actual - expected) for actual, expected in zip(centre, (245, 50, 15))) < 20, centre
        finally:
            document.close()


if __name__ == "__main__":
    check_page_box_pixels_and_alpha_flattening()
    print("Image to one-page PDF dimensions and pixels passed")
