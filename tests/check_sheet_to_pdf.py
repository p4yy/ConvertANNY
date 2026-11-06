"""Characterization check for spreadsheet-to-PDF routing and temp cleanup."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import engine


def check_sheet_to_pdf_contract():
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "table.xlsx"
        source.write_bytes(b"input")
        office_pdf = Path(directory) / "office.pdf"
        saved = engine.office_available, engine.office_convert, engine.sheet_to_html, engine.html_to_pdf_file
        try:
            engine.office_available = lambda: True
            engine.office_convert = lambda path, fmt: office_pdf
            assert engine.sheet_to_pdf(source, None) == office_pdf

            scratch = Path(directory) / "table.html"
            scratch.write_text("<table></table>", encoding="utf-8")
            called = []
            engine.office_available = lambda: False
            engine.sheet_to_html = lambda path, params: scratch
            engine.html_to_pdf_file = lambda html, output: called.append((html, output)) or output
            fallback = engine.sheet_to_pdf(source, None)
            assert fallback == Path(directory) / "table.pdf"
            assert called == [("<table></table>", fallback)]
            assert not scratch.exists()
        finally:
            engine.office_available, engine.office_convert, engine.sheet_to_html, engine.html_to_pdf_file = saved


if __name__ == "__main__":
    check_sheet_to_pdf_contract()
    print("Spreadsheet-to-PDF behavior check passed")
