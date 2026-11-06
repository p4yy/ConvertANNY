"""Characterization check for HTML-to-PDF pagination and output contract."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import engine


def check_html_to_pdf_contract():
    import pymupdf
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "rendered.pdf"
        html = "<h1>ConvertANNY Report</h1><p>First paragraph.</p>" + "<p>Long text. </p>" * 300
        try:
            assert engine.html_to_pdf_file(html, output) == output
            document = pymupdf.open(output)
            try:
                assert document.page_count >= 2
                assert all(round(page.rect.width) == 595 and round(page.rect.height) == 842 for page in document)
                text = "\n".join(page.get_text() for page in document)
                assert "ConvertANNY Report" in text and "First paragraph." in text
            finally:
                document.close()
        finally:
            engine.close_pdfs()


if __name__ == "__main__":
    check_html_to_pdf_contract()
    print("HTML-to-PDF behavior check passed")
