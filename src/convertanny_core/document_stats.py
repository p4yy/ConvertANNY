"""Document text statistics for the non-destructive Info action."""

from __future__ import annotations

import html
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from .model import ConversionError


_TEXT_PARTS = {
    "docx": ("word/document.xml", "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"),
    "odt": ("content.xml", "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}p"),
}


def _xml_text(data: bytes) -> str:
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as error:
        raise ConversionError("The document contains invalid XML") from error
    chunks = []
    paragraph_tags = ("}p",)
    for node in root.iter():
        if node.text:
            chunks.extend((node.text, " "))
        if node.tag.endswith(paragraph_tags):
            chunks.append("\n")
        if node.tail:
            chunks.append(node.tail)
    return "".join(chunks)


def _html_text(source: str) -> str:
    source = re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\1\s*>", " ", source)
    source = re.sub(r"(?i)</?(?:p|div|br|li|h[1-6]|tr)\b[^>]*>", "\n", source)
    return html.unescape(re.sub(r"<[^>]*>", " ", source))


def _plain_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1256", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    return _html_text(text) if path.suffix.lower() in (".html", ".htm") else text


def _office_text(path: Path, extension: str) -> tuple[str, int | None]:
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            pages = None
            if extension == "docx":
                parts = ["word/document.xml"]
                if "docProps/app.xml" in names:
                    app = ElementTree.fromstring(archive.read("docProps/app.xml"))
                    pages = next((int(element.text) for element in app.iter()
                                  if element.tag.endswith("}Pages") and element.text and element.text.isdigit()), None)
            elif extension == "pptx":
                parts = sorted(name for name in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", name))
                pages = len(parts)
            elif extension == "odt":
                parts = ["content.xml"]
            else:
                parts = sorted(name for name in names if name.startswith("xl/sharedStrings"))
            text = "\n".join(_xml_text(archive.read(name)) for name in parts if name in names)
            return text, pages
    except (OSError, zipfile.BadZipFile) as error:
        raise ConversionError("The document package could not be read") from error


def _pdf_text(path: Path) -> tuple[str, int]:
    try:
        import pymupdf
        with pymupdf.open(path) as document:
            return "\n".join(page.get_text() for page in document), document.page_count
    except Exception as error:
        raise ConversionError("The PDF or e-book could not be read") from error


def document_stats(source: str | Path) -> str:
    path = Path(source)
    extension = path.suffix.lower().lstrip(".")
    pages = None
    if extension in {"pdf", "epub", "xps", "oxps"}:
        text, pages = _pdf_text(path)
    elif extension in {"docx", "pptx", "odt", "xlsx"}:
        text, pages = _office_text(path, extension)
    else:
        text = _plain_text(path)
    words = re.findall(r"\w+(?:['’-]\w+)*", text, flags=re.UNICODE)
    result = {"name": path.name, "words": len(words),
              "chars": sum(not char.isspace() for char in text),
              "chars_spaces": len(text.strip()), "lines": text.count("\n") + 1 if text.strip() else 0}
    if pages is not None:
        result["pages"] = pages
    return "info:" + json.dumps(result, ensure_ascii=False)
