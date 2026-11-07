"""Verify document statistics on plain text, HTML, DOCX and PDF inputs."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import engine
import pymupdf
from docx import Document


def check():
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / "tmp") as folder:
        root = Path(folder)
        text = root / "words.txt"
        text.write_text("Two words\nand three", encoding="utf-8")
        info = json.loads(engine.count_words(text, {})[5:])
        assert (info["words"], info["lines"], info.get("pages")) == (4, 2, None)

        html = root / "words.html"
        html.write_text("<p>One <b>two</b></p><script>hidden terms</script>", encoding="utf-8")
        info = json.loads(engine.count_words(html, {})[5:])
        assert info["words"] == 2

        docx_path = root / "words.docx"
        document = Document();document.add_paragraph("First paragraph");document.add_paragraph("Second line")
        document.save(docx_path)
        info = json.loads(engine.count_words(docx_path, {})[5:])
        assert info["words"] == 4 and info["lines"] >= 2

        pdf_path = root / "words.pdf"
        document = pymupdf.open();page = document.new_page();page.insert_text((72, 72), "PDF count")
        document.save(pdf_path);document.close()
        info = json.loads(engine.count_words(pdf_path, {})[5:])
        assert info["words"] == 2 and info["pages"] == 1
    print("Document statistics passed for text, HTML, DOCX and PDF")


if __name__ == "__main__":
    check()
