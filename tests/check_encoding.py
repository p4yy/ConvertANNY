"""Check Arabic mojibake and Windows-1256 repair using temporary text only."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from convertanny_core.encoding_tools import decode_arabic_text
from convertanny_core.model import ConversionError
import engine


def check():
    arabic = "مرحبا بالعالم"
    mojibake = arabic.encode("utf-8").decode("cp1252")
    repaired, kind = decode_arabic_text(mojibake.encode("utf-8"))
    assert repaired == arabic and kind == "mojibake"
    repaired, kind = decode_arabic_text(arabic.encode("cp1256"))
    assert repaired == arabic and kind == "windows-1256"
    assert decode_arabic_text(arabic.encode("utf-8")) == (arabic, "")

    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / "tmp") as folder:
        source = Path(folder) / "arabic.txt"
        source.write_bytes(mojibake.encode("utf-8"))
        output = engine.fix_arabic_text(source, {})
        assert output.name == "arabic fixed.txt"
        assert output.read_text(encoding="utf-8-sig") == arabic
        valid = Path(folder) / "valid.txt"
        valid.write_text(arabic, encoding="utf-8")
        try:
            engine.fix_arabic_text(valid, {})
        except ConversionError as error:
            assert "already contains valid UTF-8" in str(error)
        else:
            raise AssertionError("Valid UTF-8 text should not be rewritten")
    print("Arabic UTF-8 mojibake, Windows-1256 decode, and no-op protection passed")


if __name__ == "__main__":
    check()
