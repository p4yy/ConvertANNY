"""Exercise the owned encrypted-archive writer through the app engine wrapper."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import engine
import pyzipper
import py7zr
from convertanny_core.model import ConversionError


def check():
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / "tmp") as folder:
        root = Path(folder)
        source = root / "note.txt"
        source.write_text("ConvertANNY archive verification", encoding="utf-8")

        zip_path = engine.protect_archive([str(source)], {"Password": "test-pass", "Format": "ZIP (AES-256)"})
        with pyzipper.AESZipFile(zip_path) as archive:
            archive.setpassword(b"test-pass")
            assert archive.testzip() is None
            assert archive.read("note.txt").decode() == "ConvertANNY archive verification"

        seven_path = engine.protect_archive([str(source)], {"Password": "test-pass", "Format": "7Z (AES-256)"})
        extracted = root / "seven-extracted"
        extracted.mkdir()
        with py7zr.SevenZipFile(seven_path, "r", password="test-pass") as archive:
            assert archive.list()[0].filename == "note.txt"
            archive.extractall(path=extracted)
        assert (extracted / "note.txt").read_text(encoding="utf-8") == "ConvertANNY archive verification"

        try:
            engine.protect_archive([str(source)], {"Password": "", "Format": "ZIP (AES-256)"})
        except ConversionError as error:
            assert "Password cannot be empty" in str(error)
        else:
            raise AssertionError("Empty passwords must be rejected")
    print("Owned encrypted ZIP/7Z creation, decryption and password validation passed")


if __name__ == "__main__":
    check()
