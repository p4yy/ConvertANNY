"""Check ConvertANNY tool discovery across file categories and group sizes."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import engine
import pymupdf


def ids(paths):
    return [operation.id for operation in engine.tools([str(path) for path in paths])]


def check():
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / "tmp") as folder:
        root = Path(folder)
        image, second_image = root / "one.png", root / "two.jpg"
        image.touch();second_image.touch()
        image_tools = ids([image])
        assert {"edit", "scan", "removebg", "watermark", "protect_zip", "splitparts"} <= set(image_tools)
        group_tools = ids([image, second_image])
        assert {"combine_pdf", "stitch_h", "gif", "cbz"} <= set(group_tools)

        audio = root / "sound.mp3";audio.touch()
        assert {"compress", "normalize", "trim", "transcribe"} <= set(ids([audio]))

        pdf = root / "report.pdf";other_pdf = root / "other.pdf"
        document = pymupdf.open();document.new_page();document.save(pdf);document.save(other_pdf);document.close()
        pdf_tools = ids([pdf])
        assert {"compress", "split", "pages", "protect", "arrange", "sign"} <= set(pdf_tools)
        pdf_group = ids([pdf, other_pdf])
        assert pdf_group.count("arrange") == 1 and "merge" in pdf_group

        mixed = ids([pdf, image])
        assert {"sign", "logo", "merge", "arrange"} <= set(mixed)
        text = root / "words.txt";text.write_text("text", encoding="utf-8")
        assert {"count", "fixarabic", "protect_zip", "splitparts"} <= set(ids([text]))
        package = root / "records.zip";package.touch()
        assert "extract" in ids([package])
        folder_input = root / "Folder";folder_input.mkdir()
        assert "protect_zip" in ids([folder_input])
        parts = root / "archive.zip.001";parts.touch()
        assert ids([parts]) == ["join"]
    print("Owned operation catalogue passed image, audio, PDF, mixed, text, archive, folder and part-file checks")


if __name__ == "__main__":
    check()
