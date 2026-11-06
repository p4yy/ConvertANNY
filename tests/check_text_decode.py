"""Encoding policy checks for text import."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from convertanny_core.text_decode import decode_document


def run():
    assert decode_document("hello".encode("utf-8-sig")) == "hello"
    assert decode_document("hello".encode("utf-16")) == "hello"
    assert decode_document("مرحبا".encode("cp1256")) == "مرحبا"
    assert decode_document("café".encode("cp1252")) == "café"
    assert decode_document(b"a\xffb") == "aÿb"
    print("BOM, UTF-16, Arabic Windows, Western Windows and byte-preserving fallback passed")


if __name__ == "__main__":
    run()
