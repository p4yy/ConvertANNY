"""Test PDF table extraction through the real ConvertANNY catalog operation."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import engine
import pymupdf
from openpyxl import load_workbook
from convertanny_core.model import ConversionError


def check():
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / "tmp") as folder:
        root = Path(folder)
        source = root / "table.pdf"
        document = pymupdf.open()
        page = document.new_page()
        xs, ys = [72, 220, 350], [72, 104, 136]
        for y in ys:
            page.draw_line((xs[0], y), (xs[-1], y))
        for x in xs:
            page.draw_line((x, ys[0]), (x, ys[-1]))
        page.insert_text((82, 94), "Item")
        page.insert_text((230, 94), "Count")
        page.insert_text((82, 126), "Notebook")
        page.insert_text((230, 126), "12")
        document.save(source)
        document.close()

        operation = next((op for op in engine.conversions([str(source)]) if op.id == "to_xlsx"), None)
        assert operation is not None, "PDF to XLSX must appear in the ConvertANNY conversion catalog"
        result = engine.run_op(operation, [str(source)])[0]
        workbook = load_workbook(result, read_only=True, data_only=True)
        try:
            sheet = workbook["Page 1 Table 1"]
            assert sheet["A1"].value == "Item" and sheet["B1"].value == "Count"
            assert sheet["A2"].value == "Notebook" and sheet["B2"].value == "12"
        finally:
            workbook.close()

        blank = root / "no-table.pdf"
        document = pymupdf.open();document.new_page();document.save(blank);document.close()
        try:
            engine.pdf_to_xlsx(blank, {})
        except ConversionError as error:
            assert "No extractable tables" in str(error)
        else:
            raise AssertionError("PDF with no tables should fail clearly, not create an empty workbook")
    print("PDF table detection, catalog discovery, XLSX rows and empty-table error passed")


if __name__ == "__main__":
    check()
