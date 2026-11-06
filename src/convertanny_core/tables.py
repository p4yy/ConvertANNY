"""ConvertANNY-authored spreadsheet and delimited-text transformations."""

from __future__ import annotations

import csv
import html
import json
import io
import re
from pathlib import Path

from .model import CancelToken, ConversionError
from .paths import OutputPolicy, atomic_write


def read_sheets(source: str | Path):
    source = Path(source)
    extension = source.suffix.lower()
    if extension in (".csv", ".tsv"):
        raw = source.read_bytes()
        text = None
        for encoding in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        text = text or raw.decode("utf-8", "replace")
        delimiter = "\t" if extension == ".tsv" else ","
        if extension == ".csv" and text.strip():
            try:
                delimiter = csv.Sniffer().sniff(text[:4096], ",;\t|").delimiter
            except csv.Error:
                pass
        return [(source.stem, list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)))]
    if extension in (".xlsx", ".xlsm"):
        try:
            from openpyxl import load_workbook
            workbook = load_workbook(source, read_only=True, data_only=True)
            try:
                return [(sheet.title, [list(row) for row in sheet.iter_rows(values_only=True)])
                        for sheet in workbook.worksheets]
            finally:
                workbook.close()
        except Exception as exc:
            raise ConversionError(f"Could not read {source.name}: {exc}") from exc
    raise ConversionError("Choose an XLSX, XLSM, CSV or TSV file")


def _clean(value):
    return "" if value is None else value


def _number(value):
    if not isinstance(value, str):
        return value
    text = value.strip()
    if re.fullmatch(r"-?\d+", text) and len(text) < 15 and not (len(text) > 1 and text.startswith("0")):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        try:
            return float(text)
        except ValueError:
            pass
    return value


def table_to_delimited(source: str | Path, target_format: str, *, directory=None, token=None):
    source = Path(source)
    target_format = target_format.lower().lstrip(".")
    if target_format not in ("csv", "tsv"):
        raise ConversionError("Output must be CSV or TSV")
    sheets = read_sheets(source)
    delimiter = "\t" if target_format == "tsv" else ","
    parent = Path(directory) if directory else None
    if len(sheets) == 1:
        destination = OutputPolicy(directory=parent).destination(source, target_format)
        def write(temp):
            with temp.open("w", newline="", encoding="utf-8-sig") as stream:
                csv.writer(stream, delimiter=delimiter).writerows([[_clean(v) for v in row] for row in sheets[0][1]])
        return atomic_write(destination, write, token)
    parent = parent or source.parent
    folder_base = parent / f"{source.stem} {target_format.upper()}"
    folder = folder_base
    index = 2
    while folder.exists():
        folder = parent / f"{folder_base.name} ({index})"
        index += 1
    folder.mkdir(parents=True)
    try:
        for title, rows in sheets:
            if token:
                token.check()
            safe = re.sub(r'[\\/:*?"<>|]', "_", title).strip(" .") or "Sheet"
            destination = folder / f"{safe}.{target_format}"
            with destination.open("w", newline="", encoding="utf-8-sig") as stream:
                csv.writer(stream, delimiter=delimiter).writerows([[_clean(v) for v in row] for row in rows])
        return folder
    except Exception:
        import shutil
        shutil.rmtree(folder, ignore_errors=True)
        raise


def table_to_xlsx(source: str | Path, *, directory=None, token=None):
    from openpyxl import Workbook
    source = Path(source)
    destination = OutputPolicy(directory=Path(directory) if directory else None).destination(source, "xlsx")
    def write(temp):
        workbook = Workbook()
        workbook.remove(workbook.active)
        used = set()
        for title, rows in read_sheets(source):
            if token:
                token.check()
            name = re.sub(r"[\\/*?:\[\]]", "_", title).strip("'")[:31] or "Sheet"
            unique = name
            suffix = 2
            while unique.lower() in used:
                tail = f"_{suffix}"
                unique = name[:31-len(tail)] + tail
                suffix += 1
            used.add(unique.lower())
            sheet = workbook.create_sheet(unique)
            for row in rows:
                sheet.append([_number(value) for value in row])
        workbook.save(temp)
    return atomic_write(destination, write, token)


def table_to_json(source: str | Path, *, directory=None, token=None):
    source = Path(source)
    sheets = read_sheets(source)
    data = {}
    for title, rows in sheets:
        if token:
            token.check()
        if not rows:
            data[title] = []
            continue
        headers = [str(value) if value is not None else f"col{i+1}" for i, value in enumerate(rows[0])]
        data[title] = [{headers[i]: (_number(value) if isinstance(value, str) else value)
                        for i, value in enumerate(row) if i < len(headers)} for row in rows[1:]]
    payload = next(iter(data.values())) if len(data) == 1 else data
    destination = OutputPolicy(directory=Path(directory) if directory else None).destination(source, "json")
    return atomic_write(destination, lambda temp: temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"), token)


def table_to_html(source: str | Path, *, directory=None, token=None):
    source = Path(source)
    parts = [f"<!doctype html><meta charset='utf-8'><title>{html.escape(source.stem)}</title><body>"]
    for title, rows in read_sheets(source):
        if token:
            token.check()
        parts.append(f"<h2>{html.escape(title)}</h2><table>")
        for index, row in enumerate(rows):
            cell = "th" if index == 0 else "td"
            parts.append("<tr>" + "".join(f"<{cell}>{html.escape(str(_clean(v)))}</{cell}>" for v in row) + "</tr>")
        parts.append("</table>")
    parts.append("</body>")
    destination = OutputPolicy(directory=Path(directory) if directory else None).destination(source, "html")
    return atomic_write(destination, lambda temp: temp.write_text("".join(parts), encoding="utf-8"), token)


def table_to_markdown(source: str | Path, *, directory=None, token=None):
    source = Path(source)
    sheets = read_sheets(source)
    parts = []
    for title, rows in sheets:
        if token:
            token.check()
        rows = [row for row in rows if any(value not in (None, "") for value in row)]
        if len(sheets) > 1:
            parts.append(f"## {title}\n")
        if not rows:
            continue
        width = max(len(row) for row in rows)
        rows = [list(row) + [""] * (width - len(row)) for row in rows]
        cell = lambda value: str(_clean(value)).replace("|", "\\|").replace("\n", " ")
        parts.append("| " + " | ".join(cell(value) for value in rows[0]) + " |")
        parts.append("|" + "---|" * width)
        parts.extend("| " + " | ".join(cell(value) for value in row) + " |" for row in rows[1:])
        parts.append("")
    destination = OutputPolicy(directory=Path(directory) if directory else None).destination(source, "md")
    return atomic_write(destination, lambda temp: temp.write_text("\n".join(parts), encoding="utf-8"), token)
