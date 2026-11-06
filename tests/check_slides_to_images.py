"""Characterization checks for slide image export routing and cleanup."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import engine


def check_slides_to_images_contract():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "deck.pptx"
        source.write_bytes(b"source")
        pdf = root / "deck.pdf"
        saved = engine.IS_WIN, engine._com_convert, engine.office_convert, engine.pdf_to_images, engine.OUTPUT_DIR
        try:
            engine.IS_WIN = False
            engine.office_convert = lambda path, fmt: (pdf.write_bytes(b"pdf") and pdf) if fmt == "pdf" else None

            def image_export(fmt, dpi):
                assert (fmt, dpi) == ("png", 150)
                def convert(intermediate, params):
                    folder = root / "rendered"
                    folder.mkdir()
                    (folder / "001.png").write_bytes(b"image")
                    return folder
                return convert

            engine.pdf_to_images = image_export
            result = engine.slides_to_images("png")(source, None)
            assert result == root / "deck PNG" and (result / "001.png").read_bytes() == b"image"
            assert not pdf.exists()
        finally:
            engine.IS_WIN, engine._com_convert, engine.office_convert, engine.pdf_to_images, engine.OUTPUT_DIR = saved


if __name__ == "__main__":
    check_slides_to_images_contract()
    print("Slide-to-image behavior check passed")
