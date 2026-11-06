"""Characterization check for the PDF-to-CBZ output contract."""
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import engine


def check_pdf_to_cbz_contract():
    import fitz
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "pages.pdf"
        document = fitz.open()
        document.new_page(width=72, height=36)
        document.new_page(width=36, height=72)
        document.save(source)
        document.close()

        try:
            output = engine.pdf_to_cbz(source, None)
            assert output == root / "pages.cbz"
            with zipfile.ZipFile(output) as archive:
                assert archive.namelist() == ["001.jpg", "002.jpg"]
                assert all(item.compress_type == zipfile.ZIP_STORED for item in archive.infolist())
                first_page = archive.read("001.jpg")
                assert all(archive.read(name).startswith(b"\xff\xd8") for name in archive.namelist())
            image = engine._pil()[0]
            with image.open(__import__("io").BytesIO(first_page)) as raster:
                assert raster.size == (150, 75)  # 150 DPI rasterization of a 72 x 36 pt page
        finally:
            engine.close_pdfs()


if __name__ == "__main__":
    check_pdf_to_cbz_contract()
    print("PDF-to-CBZ behavior check passed")
