"""ConvertANNY-authored text and PDF operations using MuPDF as a backend."""

from __future__ import annotations

import html
import io
import re
from contextlib import redirect_stdout
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable

try:
    import pymupdf as fitz
except ImportError:  # Keep the rest of the core importable when PDF support is absent.
    fitz = None

from .model import CancelToken, ConversionError
from .paths import OutputPolicy, atomic_write


def _require_pdf_backend():
    if fitz is None:
        raise ConversionError("PDF support requires PyMuPDF")


def _font_path() -> Path | None:
    path = Path(__file__).resolve().parents[1] / "assets" / "fonts" / "Inter-Regular.ttf"
    return path if path.is_file() else None


def _register_unicode_font(page) -> str:
    """Embed MuPDF's Unicode fallback font for lines outside Inter's text map."""
    font = fitz.Font(fontname="cjk")
    page.insert_font(fontname="ConvertANNYUnicode", fontbuffer=font.buffer)
    return "ConvertANNYUnicode"


def _wrap(font, text: str, size: float, width: float) -> list[str]:
    """Wrap one paragraph using the selected font's measured glyph advances."""
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    for word in words:
        proposed = f"{current} {word}".strip()
        if current and font.text_length(proposed, fontsize=size) > width:
            lines.append(current)
            current = word
        else:
            current = proposed
        # Split pathological tokens such as a pasted hash or minified source line.
        if font.text_length(current, fontsize=size) > width:
            chars: list[str] = []
            for char in current:
                test = "".join(chars) + char
                if chars and font.text_length(test, fontsize=size) > width:
                    lines.append("".join(chars))
                    chars = [char]
                else:
                    chars.append(char)
            current = "".join(chars)
    if current or not lines:
        lines.append(current)
    return lines


def _markdown_blocks(text: str) -> Iterable[tuple[str, str]]:
    """Read a small, predictable Markdown subset without executing embedded HTML."""
    in_code = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.strip().startswith("```") or line.strip().startswith("~~~"):
            in_code = not in_code
            continue
        if not line:
            yield "space", ""
            continue
        if in_code:
            yield "code", line
            continue
        heading = re.match(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$", line)
        if heading:
            yield "heading", heading.group(2)
            continue
        bullet = re.match(r"^\s*([-+*]|\d+[.)])\s+(.*)$", line)
        if bullet:
            yield "bullet", "• " + bullet.group(2)
            continue
        line = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", line)
        line = re.sub(r"`([^`]*)`", r"\1", line)
        line = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), line)
        line = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)|(?<!_)_([^_]+)_(?!_)", lambda m: m.group(1) or m.group(2), line)
        yield "body", line


class _HTMLText(HTMLParser):
    """Extract readable blocks from HTML without running scripts or fetching assets."""

    BLOCKS = {"p": "body", "div": "body", "h1": "heading", "h2": "heading",
              "h3": "heading", "h4": "heading", "h5": "heading", "h6": "heading",
              "li": "bullet", "pre": "code", "blockquote": "body", "br": "space"}
    IGNORED = {"script", "style", "noscript", "svg", "head"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, str]] = []
        self._kind = "body"
        self._parts: list[str] = []
        self._ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.IGNORED:
            self._ignored += 1
        if tag in self.BLOCKS:
            self._flush()
            self._kind = self.BLOCKS[tag]

    def handle_endtag(self, tag):
        if tag in self.IGNORED and self._ignored:
            self._ignored -= 1
        if tag in self.BLOCKS:
            self._flush()

    def handle_data(self, data):
        if not self._ignored and data.strip():
            self._parts.append(data)

    def _flush(self):
        value = re.sub(r"\s+", " ", " ".join(self._parts)).strip()
        if value:
            self.blocks.append((self._kind, ("• " if self._kind == "bullet" else "") + value))
        self._parts.clear()
        self._kind = "body"


def text_to_html_file(source: str | Path, *, policy: OutputPolicy | None = None,
                      token: CancelToken | None = None) -> Path:
    """Render TXT, Markdown or HTML input into a self-contained safe HTML file."""
    source = Path(source)
    suffix = source.suffix.lower()
    try:
        raw = _read_text(source)
    except OSError as exc:
        raise ConversionError(f"Could not read {source.name}: {exc}") from exc
    if suffix in (".html", ".htm"):
        parser = _HTMLText()
        parser.feed(raw)
        parser.close()
        parser._flush()
        blocks = parser.blocks
        contents = "".join(f"<h2>{html.escape(value)}</h2>" if kind == "heading" else
                            f"<pre>{html.escape(value)}</pre>" if kind == "code" else
                            f"<p>{html.escape(value)}</p>" for kind, value in blocks)
    elif suffix in (".md", ".markdown"):
        rendered = []
        for kind, value in _markdown_blocks(raw):
            if token:
                token.check()
            if kind == "heading":
                rendered.append(f"<h2>{html.escape(value)}</h2>")
            elif kind == "bullet":
                rendered.append(f"<ul><li>{html.escape(value.removeprefix('• '))}</li></ul>")
            elif kind == "body":
                rendered.append(f"<p>{html.escape(value)}</p>")
            elif kind == "code":
                rendered.append(f"<pre>{html.escape(value)}</pre>")
        contents = "".join(rendered)
    else:
        contents = "".join(f"<p>{html.escape(line)}</p>" for line in raw.splitlines())
    document = ("<!doctype html><html><head><meta charset=\"utf-8\"><title>" +
                html.escape(source.stem) + "</title><style>body{font:16px/1.6 Inter,Arial,sans-serif;max-width:860px;margin:40px auto;padding:0 24px;color:#1b2430}h1,h2,h3{line-height:1.25}pre{white-space:pre-wrap;background:#f4f6f8;padding:12px;border-radius:8px}</style></head><body>" + contents + "</body></html>")
    destination = (policy or OutputPolicy()).destination(source, "html")
    return atomic_write(destination, lambda temp: temp.write_text(document, encoding="utf-8"), token)


class _HTMLMarkdown(HTMLParser):
    """Convert basic HTML text structure into readable ATX Markdown."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._buffer: list[str] = []
        self._heading = 0
        self._list_depth = 0
        self._ignored_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "head"):
            self._ignored_depth += 1
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._flush()
            self._heading = int(tag[1])
        elif tag == "ul" or tag == "ol":
            self._flush()
            self._list_depth += 1
        elif tag == "br":
            self._buffer.append("  ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "head"):
            self._ignored_depth = max(0, self._ignored_depth - 1)
        elif tag in ("p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "pre"):
            self._flush()
        elif tag in ("ul", "ol"):
            self._list_depth = max(0, self._list_depth - 1)

    def handle_data(self, data):
        if not self._ignored_depth and data.strip():
            self._buffer.append(data.strip())

    def _flush(self):
        text = re.sub(r"\s+", " ", " ".join(self._buffer)).strip()
        if text:
            if self._heading:
                text = f"{'#' * self._heading} {text}"
                self._heading = 0
            elif self._list_depth:
                text = "- " + text
            self.parts.append(text)
        self._buffer.clear()


def html_to_markdown_file(source: str | Path, *, policy: OutputPolicy | None = None,
                          token: CancelToken | None = None) -> Path:
    source = Path(source)
    parser = _HTMLMarkdown()
    parser.feed(_read_text(source))
    parser.close()
    parser._flush()
    destination = (policy or OutputPolicy()).destination(source, "md")
    return atomic_write(destination, lambda temp: temp.write_text("\n\n".join(parser.parts) + "\n", encoding="utf-8"), token)


def markdown_to_text_file(source: str | Path, *, policy: OutputPolicy | None = None,
                          token: CancelToken | None = None) -> Path:
    """Remove Markdown presentation markers while preserving readable text and code."""
    source = Path(source)
    lines = _read_text(source).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    result = []
    in_fence = False
    for line in lines:
        if token:
            token.check()
        if re.match(r"^\s*(```+|~~~+)", line):
            in_fence = not in_fence
            continue
        if not in_fence:
            line = re.sub(r"^\s{0,3}#{1,6}\s+", "", line)
            line = re.sub(r"^\s*>\s?", "", line)
            line = re.sub(r"^\s*(?:[-+*]|\d+[.)])\s+", "", line)
            line = re.sub(r"^\s*(?:[-*_]\s*){3,}$", "", line)
            line = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", line)
            line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line)
            line = re.sub(r"<([^>]+)>", r"\1", line)
            line = re.sub(r"(?<!\\)(?:\*\*|__)(.+?)(?:\*\*|__)", r"\1", line)
            line = re.sub(r"(?<!\\)(?:\*|_)([^*_]+)(?:\*|_)", r"\1", line)
            line = re.sub(r"(?<!\\)`([^`]+)`", r"\1", line)
            line = line.replace("\\*", "*").replace("\\_", "_").replace("\\`", "`")
        result.append(html.unescape(line))
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(result)).strip()
    destination = (policy or OutputPolicy()).destination(source, "txt")
    return atomic_write(destination, lambda temp: temp.write_text(text + "\n", encoding="utf-8"), token)


def text_to_docx(source: str | Path, *, policy: OutputPolicy | None = None,
                 token: CancelToken | None = None) -> Path:
    """Create an editable Word document from plain text, Markdown or HTML blocks."""
    source = Path(source)
    try:
        from docx import Document
        from docx.shared import Pt
    except ImportError as exc:
        raise ConversionError("DOCX export requires python-docx") from exc
    suffix = source.suffix.lower()
    raw = _read_text(source)
    destination = (policy or OutputPolicy()).destination(source, "docx")
    def write(temp: Path):
        document = Document()
        document.core_properties.title = source.stem
        document.core_properties.author = "ConvertANNY"
        if suffix in (".html", ".htm"):
            parser = _HTMLText()
            parser.feed(raw)
            parser.close()
            parser._flush()
            blocks = parser.blocks
        elif suffix in (".md", ".markdown"):
            blocks = list(_markdown_blocks(raw))
        else:
            blocks = [("body", line) for line in raw.splitlines()]
        for kind, value in blocks:
            if token:
                token.check()
            if kind == "space" or not value.strip():
                continue
            if kind == "heading":
                paragraph = document.add_paragraph(style="Heading 2")
                paragraph.add_run(value).font.size = Pt(16)
            elif kind == "bullet":
                document.add_paragraph(value.removeprefix("• "), style="List Bullet")
            elif kind == "code":
                paragraph = document.add_paragraph()
                run = paragraph.add_run(value)
                run.font.name = "Consolas"
                run.font.size = Pt(9)
            else:
                document.add_paragraph(value)
        document.save(temp)
        if token:
            token.report(1)
    return atomic_write(destination, write, token)


def _read_text(source: Path) -> str:
    data = source.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _write_text_pdf(source: Path, output: Path, markdown: bool, token: CancelToken | None = None) -> None:
    _require_pdf_backend()
    try:
        text = source.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        raise ConversionError(f"Could not read {source.name}: {exc}") from exc
    doc = fitz.open()
    fontfile = str(_font_path()) if _font_path() else None
    page_width, page_height = 595.28, 841.89
    margin_x, margin_y = 52.0, 52.0
    y_limit = page_height - margin_y
    page = doc.new_page(width=page_width, height=page_height)
    y = margin_y

    def new_page():
        nonlocal page, y
        page = doc.new_page(width=page_width, height=page_height)
        y = margin_y

    def draw(text_line: str, *, size: float, bold: bool = False, color=(0.12, 0.14, 0.18), indent: float = 0):
        nonlocal y
        font_name = "Inter" if fontfile else ("hebo" if bold else "helv")
        font = fitz.Font(fontfile=fontfile) if fontfile else fitz.Font(fontname=font_name)
        width = page_width - 2 * margin_x - indent
        lines = _wrap(font, text_line, size, width)
        line_height = size * (1.48 if size < 16 else 1.32)
        for piece in lines:
            if y + line_height > y_limit:
                new_page()
            if piece:
                if any(ord(char) > 127 for char in piece):
                    unicode_font = _register_unicode_font(page)
                    page.insert_text((margin_x + indent, y + size), piece, fontname=unicode_font,
                                     fontsize=size, color=color)
                else:
                    page.insert_text((margin_x + indent, y + size), piece, fontname=font_name,
                                     fontsize=size, color=color, fontfile=fontfile if font_name == "Inter" else None)
            y += line_height

    if not markdown:
        for line in text.splitlines() or [""]:
            if token:
                token.check()
            draw(line, size=10.5, color=(0.12, 0.14, 0.18))
        if token:
            token.report(1)
    else:
        for kind, value in _markdown_blocks(text):
            if token:
                token.check()
            if kind == "space":
                y += 5
            elif kind == "heading":
                draw(value, size=19 if y == margin_y else 15, bold=True, color=(0.08, 0.19, 0.35))
                y += 3
            elif kind == "code":
                draw(value, size=9.5, color=(0.12, 0.23, 0.38), indent=10)
            elif kind == "bullet":
                draw(value, size=10.5, indent=8)
            else:
                draw(value, size=10.5)
        if token:
            token.report(1)
    try:
        doc.set_metadata({"title": source.stem, "author": "ConvertANNY"})
        doc.save(output, garbage=3, deflate=True)
    finally:
        doc.close()


def text_to_pdf(source: str | Path, *, markdown: bool = False, policy: OutputPolicy | None = None,
                token: CancelToken | None = None) -> Path:
    source = Path(source)
    if source.suffix.lower() not in (".txt", ".md", ".markdown", ".html", ".htm"):
        raise ConversionError("Choose a text, Markdown or HTML file")
    destination = (policy or OutputPolicy()).destination(source, "pdf")
    if source.suffix.lower() in (".html", ".htm"):
        try:
            parser = _HTMLText()
            parser.feed(_read_text(source))
            parser.close()
            parser._flush()
            blocks = parser.blocks
        except (OSError, ValueError) as exc:
            raise ConversionError(f"Could not read {source.name}: {exc}") from exc
        return atomic_write(destination, lambda temp: _write_blocks_pdf(source, temp, blocks, token), token)
    return atomic_write(destination, lambda temp: _write_text_pdf(source, temp, markdown, token), token)


def _write_blocks_pdf(source: Path, output: Path, blocks: Iterable[tuple[str, str]],
                      token: CancelToken | None = None) -> None:
    """Render extracted HTML content with the same clean, readable page layout."""
    _require_pdf_backend()
    doc = fitz.open()
    page = doc.new_page(width=595.28, height=841.89)
    fontfile_path = _font_path()
    fontfile = str(fontfile_path) if fontfile_path else None
    y = 52.0
    bottom = 789.89

    def next_page():
        nonlocal page, y
        page = doc.new_page(width=595.28, height=841.89)
        y = 52.0

    def draw(kind: str, value: str):
        nonlocal y
        size = 18.0 if kind == "heading" else (9.5 if kind == "code" else 10.5)
        font_name = "Inter" if fontfile and kind != "code" else ("cour" if kind == "code" else ("helv"))
        font = fitz.Font(fontfile=fontfile) if font_name == "Inter" else fitz.Font(fontname=font_name)
        indent = 8.0 if kind in ("bullet", "code") else 0.0
        lines = _wrap(font, value, size, 491.28 - indent)
        step = size * (1.4 if kind == "heading" else 1.5)
        for line in lines:
            if y + step > bottom:
                next_page()
            if line:
                color = (0.08, 0.19, 0.35) if kind == "heading" else (0.12, 0.14, 0.18)
                if any(ord(char) > 127 for char in line):
                    unicode_font = _register_unicode_font(page)
                    page.insert_text((52 + indent, y + size), line, fontname=unicode_font,
                                     fontsize=size, color=color)
                else:
                    page.insert_text((52 + indent, y + size), line, fontname=font_name,
                                     fontsize=size, color=color,
                                     fontfile=fontfile if font_name == "Inter" else None)
            y += step
        if kind == "heading":
            y += 4

    try:
        for kind, value in blocks:
            if token:
                token.check()
            draw(kind, value)
        doc.set_metadata({"title": source.stem, "author": "ConvertANNY"})
        doc.save(output, garbage=3, deflate=True)
        if token:
            token.report(1)
    finally:
        doc.close()


def images_to_pdf(sources: Iterable[str | Path], *, policy: OutputPolicy | None = None,
                  token: CancelToken | None = None) -> Path:
    _require_pdf_backend()
    paths = [Path(p) for p in sources]
    if not paths:
        raise ConversionError("Select at least one image")
    destination = (policy or OutputPolicy()).destination(paths[0], "pdf")
    def write(temp: Path):
        doc = fitz.open()
        try:
            for index, path in enumerate(paths):
                if token:
                    token.check()
                if not path.is_file():
                    raise ConversionError(f"File not found: {path}")
                page = doc.new_page(width=595.28, height=841.89)
                page_rect = page.rect
                page.insert_image(page_rect, filename=str(path), keep_proportion=True, overlay=True)
                if token:
                    token.report((index + 1) / len(paths))
            doc.save(temp, garbage=3, deflate=True)
        finally:
            doc.close()
    return atomic_write(destination, write, token)


def _open_pdf_or_image(path: Path):
    """Open a PDF or turn one raster image into a one-page PDF document."""
    try:
        document = fitz.open(path)
        if document.is_pdf:
            return document
        data = document.convert_to_pdf()
        document.close()
        return fitz.open("pdf", data)
    except Exception as direct_error:
        try:
            from PIL import Image
            import io
            with Image.open(path) as opened:
                image = opened.convert("RGB")
                stream = io.BytesIO()
                image.save(stream, format="PDF", resolution=150)
            return fitz.open("pdf", stream.getvalue())
        except Exception as image_error:
            raise ConversionError(f"Could not add {path.name} to the PDF: {image_error}") from direct_error


def merge_pdfs(sources: Iterable[str | Path], *, policy: OutputPolicy | None = None,
               token: CancelToken | None = None) -> Path:
    _require_pdf_backend()
    paths = [Path(p) for p in sources]
    if len(paths) < 2:
        raise ConversionError("Select at least two PDF files")
    destination = (policy or OutputPolicy()).destination(paths[0], "pdf")
    def write(temp: Path):
        merged = fitz.open()
        bookmarks = []
        try:
            for index, path in enumerate(paths):
                if token:
                    token.check()
                if not path.is_file():
                    raise ConversionError(f"File not found: {path}")
                with _open_pdf_or_image(path) as source:
                    offset = merged.page_count
                    merged.insert_pdf(source, links=True, annots=True, widgets=True)
                    for entry in source.get_toc(simple=False):
                        level, title, page_number, details = entry
                        details = dict(details)
                        details.pop("xref", None)
                        if details.get("kind") == fitz.LINK_GOTO and details.get("page", -1) >= 0:
                            details["page"] += offset
                        bookmarks.append([level, title, page_number + offset if page_number > 0 else page_number, details])
                if token:
                    token.report((index + 1) / len(paths))
            if bookmarks:
                merged.set_toc(bookmarks)
            merged.save(temp, garbage=3, deflate=True)
        finally:
            merged.close()
    return atomic_write(destination, write, token)


def _page_indexes(spec: str, count: int) -> list[int]:
    indexes: list[int] = []
    try:
        for part in str(spec).replace(" ", "").split(","):
            if not part:
                continue
            if "-" in part:
                start, end = part.split("-", 1)
                first, last = int(start or 1), int(end or count)
                if last < first:
                    raise ValueError
                indexes.extend(range(first - 1, last))
            else:
                indexes.append(int(part) - 1)
    except ValueError as exc:
        raise ConversionError("Enter pages such as 1-3,5") from exc
    if not indexes or any(index < 0 or index >= count for index in indexes):
        raise ConversionError(f"Pages must be between 1 and {count}")
    return indexes


def extract_pdf_pages(source: str | Path, pages: str, *, policy: OutputPolicy | None = None,
                      token: CancelToken | None = None) -> Path:
    """Copy selected pages to a new PDF, preserving order and repeated pages."""
    _require_pdf_backend()
    source = Path(source)
    destination = (policy or OutputPolicy(suffix=" pages")).destination(source, "pdf")
    def write(temp: Path):
        with fitz.open(source) as original:
            selected = _page_indexes(pages, original.page_count)
            output = fitz.open()
            try:
                for index, page in enumerate(selected):
                    if token:
                        token.check()
                    output.insert_pdf(original, from_page=page, to_page=page)
                    if token:
                        token.report((index + 1) / len(selected))
                output.save(temp, garbage=3, deflate=True)
            finally:
                output.close()
    return atomic_write(destination, write, token)


def split_pdf(source: str | Path, *, directory: str | Path | None = None,
              token: CancelToken | None = None) -> Path:
    """Write one-page PDFs into a fresh sibling folder; remove partial results on failure."""
    _require_pdf_backend()
    source = Path(source)
    parent = Path(directory) if directory else source.parent
    parent.mkdir(parents=True, exist_ok=True)
    base = parent / f"{source.stem} pages"
    folder = base
    number = 2
    while folder.exists():
        folder = parent / f"{base.name} ({number})"
        number += 1
    folder.mkdir()
    try:
        with fitz.open(source) as original:
            width = len(str(original.page_count))
            for index in range(original.page_count):
                if token:
                    token.check()
                output = fitz.open()
                try:
                    output.insert_pdf(original, from_page=index, to_page=index)
                    destination = folder / f"{source.stem} - {index + 1:0{width}d}.pdf"
                    output.save(destination, garbage=3, deflate=True)
                finally:
                    output.close()
                if token:
                    token.report((index + 1) / original.page_count)
        return folder
    except Exception:
        import shutil
        shutil.rmtree(folder, ignore_errors=True)
        raise


def pdf_to_text(source: str | Path, *, policy: OutputPolicy | None = None,
                token: CancelToken | None = None) -> Path:
    """Extract searchable PDF text in page order as UTF-8."""
    _require_pdf_backend()
    source = Path(source)
    destination = (policy or OutputPolicy()).destination(source, "txt")
    def write(temp: Path):
        with fitz.open(source) as document, temp.open("w", encoding="utf-8", newline="\n") as stream:
            for index, page in enumerate(document):
                if token:
                    token.check()
                if index:
                    stream.write("\n\n")
                stream.write(page.get_text())
                if token:
                    token.report((index + 1) / max(1, document.page_count))
    return atomic_write(destination, write, token)


def pdf_to_images(source: str | Path, image_format: str, *, dpi: int = 200,
                  directory: str | Path | None = None, token: CancelToken | None = None):
    """Rasterize PDF pages to PNG or JPEG, returning one file or a result folder."""
    _require_pdf_backend()
    source = Path(source)
    image_format = image_format.lower().lstrip(".")
    if image_format not in ("png", "jpg", "jpeg"):
        raise ConversionError("PDF pages can be exported as PNG or JPEG")
    if not 36 <= int(dpi) <= 1200:
        raise ConversionError("Resolution must be between 36 and 1200 DPI")
    extension = "jpg" if image_format in ("jpg", "jpeg") else "png"
    parent = Path(directory) if directory else source.parent
    with fitz.open(source) as document:
        if document.page_count == 1:
            output = OutputPolicy(directory=parent).destination(source, extension)
            image_type = "jpeg" if extension == "jpg" else "png"
            return atomic_write(output, lambda tmp: tmp.write_bytes(document[0].get_pixmap(dpi=dpi).tobytes(image_type)), token)
        base = parent / f"{source.stem} {extension.upper()}"
        folder = base
        suffix = 2
        while folder.exists():
            folder = parent / f"{base.name} ({suffix})"
            suffix += 1
        folder.mkdir(parents=True)
        width = len(str(document.page_count))
        try:
            for index, page in enumerate(document):
                if token:
                    token.check()
                output = folder / f"{source.stem} - {index + 1:0{width}d}.{extension}"
                page.get_pixmap(dpi=dpi).save(output)
                if token:
                    token.report((index + 1) / document.page_count)
            return folder
        except Exception:
            import shutil
            shutil.rmtree(folder, ignore_errors=True)
            raise


def grayscale_pdf(source: str | Path, *, policy: OutputPolicy | None = None,
                  token: CancelToken | None = None) -> Path:
    """Recolor page content to grayscale and save an optimized copy."""
    _require_pdf_backend()
    source = Path(source)
    destination = (policy or OutputPolicy(suffix=" grayscale")).destination(source, "pdf")
    def write(temp: Path):
        with fitz.open(source) as document:
            for index, page in enumerate(document):
                if token:
                    token.check()
                page.recolor(1)
                if token:
                    token.report((index + 1) / max(1, document.page_count))
            document.save(temp, garbage=4, deflate=True, deflate_images=True, clean=True)
    return atomic_write(destination, write, token)


def ebook_to_pdf(source: str | Path, *, policy: OutputPolicy | None = None,
                 token: CancelToken | None = None) -> Path:
    """Render an EPUB to PDF using the bundled MuPDF document renderer."""
    _require_pdf_backend()
    source = Path(source)
    destination = (policy or OutputPolicy()).destination(source, "pdf")
    def write(temp: Path):
        if token:
            token.check()
        try:
            with fitz.open(source) as ebook:
                if not ebook.page_count:
                    raise ConversionError("The e-book has no readable pages")
                pdf_bytes = ebook.convert_to_pdf()
            with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
                pdf.save(temp, garbage=3, deflate=True)
        except ConversionError:
            raise
        except Exception as exc:
            raise ConversionError(f"Could not render {source.name} as PDF: {exc}") from exc
        if token:
            token.report(1.0)
    return atomic_write(destination, write, token)


_ARABIC_LIGATURE_FIX = {"اإل": "الإ", "األ": "الأ", "اآل": "الآ", "اإ ل": "الإ", "اال": "الا"}


def ebook_to_text(source: str | Path, *, policy: OutputPolicy | None = None,
                  token: CancelToken | None = None) -> Path:
    """Extract readable EPUB text in reading order, retaining the existing Arabic fixes."""
    _require_pdf_backend()
    source = Path(source)
    destination = (policy or OutputPolicy()).destination(source, "txt")
    def write(temp: Path):
        try:
            with fitz.open(source) as ebook:
                pages = []
                count = ebook.page_count
                for index, page in enumerate(ebook):
                    if token:
                        token.check()
                    pages.append(page.get_text("text", sort=True))
                    if token:
                        token.report((index + 1) / max(1, count))
            text = "\n\n".join(pages)
            for bad, good in _ARABIC_LIGATURE_FIX.items():
                text = text.replace(bad, good)
            temp.write_text(text, encoding="utf-8")
        except Exception as exc:
            if isinstance(exc, ConversionError):
                raise
            raise ConversionError(f"Could not extract text from {source.name}: {exc}") from exc
    return atomic_write(destination, write, token)


def compress_pdf(source: str | Path, *, policy: OutputPolicy | None = None,
                 token: CancelToken | None = None) -> Path:
    """Repack a PDF and downsample embedded images where MuPDF can do so safely."""
    _require_pdf_backend()
    source = Path(source)
    destination = (policy or OutputPolicy(suffix=" compressed")).destination(source, "pdf")
    def write(temp: Path):
        with fitz.open(source) as document:
            try:
                document.rewrite_images(dpi_threshold=160, dpi_target=150, quality=70,
                                        lossy=True, lossless=True, bitonal=True, color=True, gray=True)
            except (AttributeError, RuntimeError, ValueError):
                pass
            try:
                document.subset_fonts()
            except (AttributeError, RuntimeError, ValueError):
                pass
            if token:
                token.check()
            document.save(temp, garbage=4, deflate=True, deflate_images=True,
                          deflate_fonts=True, clean=True)
    return atomic_write(destination, write, token)


def protect_pdf(source: str | Path, password: str, *, policy: OutputPolicy | None = None,
                token: CancelToken | None = None) -> Path:
    _require_pdf_backend()
    if not password:
        raise ConversionError("Password cannot be empty")
    source = Path(source)
    destination = (policy or OutputPolicy(suffix=" protected")).destination(source, "pdf")
    def write(temp: Path):
        with fitz.open(source) as document:
            document.save(temp, encryption=fitz.PDF_ENCRYPT_AES_256,
                          user_pw=password, owner_pw=password, garbage=3, deflate=True)
    return atomic_write(destination, write, token)


def unlock_pdf(source: str | Path, password: str, *, policy: OutputPolicy | None = None,
               token: CancelToken | None = None) -> Path:
    _require_pdf_backend()
    source = Path(source)
    destination = (policy or OutputPolicy(suffix=" unlocked")).destination(source, "pdf")
    def write(temp: Path):
        with fitz.open(source) as document:
            if document.needs_pass and not document.authenticate(password or ""):
                raise ConversionError("Wrong password")
            if token:
                token.check()
            document.save(temp, encryption=fitz.PDF_ENCRYPT_NONE, garbage=3, deflate=True)
    return atomic_write(destination, write, token)


def extract_pdf_images(source: str | Path, *, directory: str | Path | None = None,
                       token: CancelToken | None = None) -> Path:
    _require_pdf_backend()
    source = Path(source)
    parent = Path(directory) if directory else source.parent
    base = parent / f"{source.stem} images"
    folder = base
    suffix = 2
    while folder.exists():
        folder = parent / f"{base.name} ({suffix})"
        suffix += 1
    folder.mkdir(parents=True, exist_ok=True)
    seen = set()
    count = 0
    try:
        with fitz.open(source) as document:
            for page_index, page in enumerate(document, 1):
                if token:
                    token.check()
                for entry in page.get_images(full=True):
                    xref = entry[0]
                    if xref in seen:
                        continue
                    seen.add(xref)
                    image = document.extract_image(xref)
                    count += 1
                    output = folder / f"page{page_index}-{count}.{image['ext']}"
                    output.write_bytes(image["image"])
                    if token:
                        token.report(min(0.99, page_index / max(1, document.page_count)))
        if not count:
            raise ConversionError("No embedded images found")
        if token:
            token.report(1)
        return folder
    except Exception:
        import shutil
        shutil.rmtree(folder, ignore_errors=True)
        raise


def number_pdf_pages(source: str | Path, position: str = "Bottom center", style: str = "1",
                     *, policy: OutputPolicy | None = None, token: CancelToken | None = None) -> Path:
    """Add page numbers in a visible-page coordinate system, including rotated pages."""
    _require_pdf_backend()
    from html import escape
    source = Path(source)
    valid_positions = {"Bottom center", "Bottom right", "Bottom left", "Top center", "Top right", "Top left"}
    valid_styles = {"1", "1 / 12", "Page 1 of 12", "١", "صفحة ١ من ١٢"}
    if position not in valid_positions:
        raise ConversionError("Choose a supported page-number position")
    if style not in valid_styles:
        raise ConversionError("Choose a supported page-number style")
    destination = (policy or OutputPolicy(suffix=" numbered")).destination(source, "pdf")
    def write(temp: Path):
        with fitz.open(source) as document:
            total = document.page_count
            for index, page in enumerate(document, 1):
                if token:
                    token.check()
                arabic_digits = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
                text = (str(index) if style == "1" else f"{index} / {total}" if style == "1 / 12"
                        else f"Page {index} of {total}" if style == "Page 1 of 12"
                        else str(index).translate(arabic_digits) if style == "١"
                        else f"صفحة {index} من {total}".translate(arabic_digits))
                rect = page.rect
                size = max(8.0, min(rect.width, rect.height) / 55)
                margin = max(18.0, size * 2)
                height = size * 2
                y = rect.height - margin - height / 2 if position.startswith("Bottom") else margin - height / 2
                left, right = margin, rect.width - margin
                align = "right" if position.endswith("right") else "left" if position.endswith("left") else "center"
                area = fitz.Rect(left, y, right, y + height) * page.derotation_matrix
                direction = "rtl" if style == "صفحة ١ من ١٢" else "ltr"
                markup = f'<p dir="{direction}" style="font-family:sans-serif;font-size:{size}px;color:#333;text-align:{align};margin:0">{escape(text)}</p>'
                page.insert_htmlbox(area, markup, rotate=page.rotation)
                if token:
                    token.report(index / max(1, total))
            document.save(temp, garbage=3, deflate=True)
    return atomic_write(destination, write, token)


def watermark_pdf(source: str | Path, text: str = "CONFIDENTIAL", *, logo: str | Path | None = None,
                  angle: float = 45, opacity: float = 0.22,
                  size: float = 0.8, color: str = "#808080", policy: OutputPolicy | None = None,
                  token: CancelToken | None = None) -> Path:
    """Stamp text or a logo over each page with bounded opacity and validated settings."""
    _require_pdf_backend()
    source = Path(source)
    text = str(text or "CONFIDENTIAL").strip()
    if not text and not logo:
        raise ConversionError("Watermark text cannot be empty")
    try:
        opacity = max(0.0, min(1.0, float(opacity)))
        size = max(0.1, min(1.0, float(size)))
        angle = float(angle)
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise ConversionError("Watermark settings are invalid") from exc
    rgb = tuple(int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    logo_data = None
    if logo:
        try:
            from PIL import Image
            with Image.open(logo) as opened:
                image = opened.convert("RGBA")
                alpha = image.getchannel("A").point(lambda value: round(value * opacity))
                image.putalpha(alpha)
                image.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
                if angle % 360:
                    image = image.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
                import io
                stream = io.BytesIO()
                image.save(stream, format="PNG", optimize=True)
                logo_data = stream.getvalue()
        except (OSError, ValueError) as exc:
            raise ConversionError(f"Could not read watermark image: {exc}") from exc
    destination = (policy or OutputPolicy(suffix=" watermarked")).destination(source, "pdf")
    def write(temp: Path):
        with fitz.open(source) as document:
            for index, page in enumerate(document):
                if token:
                    token.check()
                rect = page.rect
                if logo_data:
                    width = rect.width * size
                    height = rect.height * size
                    box = fitz.Rect((rect.width - width) / 2, (rect.height - height) / 2,
                                    (rect.width + width) / 2, (rect.height + height) / 2)
                    page.insert_image(box * page.derotation_matrix, stream=logo_data,
                                      keep_proportion=True, overlay=True)
                else:
                    font = fitz.Font(fontname="helv")
                    font_size = max(12, min(rect.width, rect.height) * size / 8)
                    width = font.text_length(text, fontsize=font_size)
                    x = max(8, (rect.width - width) / 2)
                    y = rect.height / 2
                    pivot = fitz.Point(rect.width / 2, rect.height / 2)
                    page.insert_text((x, y), text, fontname="helv", fontsize=font_size,
                                     color=rgb, fill_opacity=opacity,
                                     morph=(pivot, fitz.Matrix(angle)))
                if token:
                    token.report((index + 1) / max(1, document.page_count))
            document.save(temp, garbage=3, deflate=True)
    return atomic_write(destination, write, token)


def arrange_pdf(sources, pages, *, policy: OutputPolicy | None = None,
                token: CancelToken | None = None) -> Path:
    """Assemble a new PDF from ordered source page references and quarter turns."""
    _require_pdf_backend()
    sources = [Path(path) for path in sources]
    if not sources or not pages:
        raise ConversionError("No pages left")
    first_pdf = next((path for path in sources if path.suffix.lower() == ".pdf"), sources[0])
    destination = (policy or OutputPolicy(suffix=" arranged")).destination(first_pdf, "pdf")
    def write(temp: Path):
        opened = {}
        output = fitz.open()
        try:
            for position, item in enumerate(pages):
                if token:
                    token.check()
                if len(item) != 3:
                    raise ConversionError("Invalid page layout entry")
                source_index, page_index, rotation = map(int, item)
                if not 0 <= source_index < len(sources):
                    raise ConversionError("A page refers to an unknown source file")
                if source_index not in opened:
                    opened[source_index] = _open_pdf_or_image(sources[source_index])
                source_doc = opened[source_index]
                if not 0 <= page_index < source_doc.page_count:
                    raise ConversionError("A page number is outside its source document")
                output.insert_pdf(source_doc, from_page=page_index, to_page=page_index)
                output[-1].set_rotation((output[-1].rotation + rotation) % 360)
                if token:
                    token.report((position + 1) / len(pages))
            output.save(temp, garbage=3, deflate=True)
        finally:
            output.close()
            for document in opened.values():
                document.close()
    return atomic_write(destination, write, token)


def sign_pdf(source: str | Path, signature: str | Path, placements, *, policy: OutputPolicy | None = None,
             token: CancelToken | None = None) -> Path:
    """Apply a user-provided signature image to normalized page rectangles."""
    _require_pdf_backend()
    if not signature:
        raise ConversionError("No signature image was placed")
    source, signature = Path(source), Path(signature)
    if not signature.is_file():
        raise ConversionError("Signature image was not found")
    if not placements:
        raise ConversionError("No signature was placed")
    destination = (policy or OutputPolicy(suffix=" signed")).destination(source, "pdf")
    def write(temp: Path):
        with fitz.open(source) as document:
            for placement in placements:
                if token:
                    token.check()
                page_index = int(placement.get("page", 0))
                if not 0 <= page_index < document.page_count:
                    raise ConversionError("Signature placement refers to an invalid page")
                page = document[page_index]
                x0, y0, x1, y1 = [float(value) for value in placement.get("rect", [0.6, 0.8, 0.9, 0.9])]
                if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
                    raise ConversionError("Signature placement is outside the page")
                visible = page.rect
                box = fitz.Rect(x0 * visible.width, y0 * visible.height,
                                x1 * visible.width, y1 * visible.height) * page.derotation_matrix
                page.insert_image(box, filename=str(signature), rotate=page.rotation,
                                  keep_proportion=True, overlay=True)
            document.save(temp, garbage=3, deflate=True)
    return atomic_write(destination, write, token)


def pdf_to_markdown(source: str | Path, *, policy: OutputPolicy | None = None,
                    token: CancelToken | None = None) -> Path:
    """Extract page text with a conservative heading heuristic into Markdown."""
    _require_pdf_backend()
    source = Path(source)
    destination = (policy or OutputPolicy()).destination(source, "md")
    def write(temp: Path):
        parts = []
        with fitz.open(source) as document:
            for page_index, page in enumerate(document):
                if token:
                    token.check()
                blocks = page.get_text("dict")["blocks"]
                sizes = [span["size"] for block in blocks for line in block.get("lines", [])
                         for span in line.get("spans", []) if span["text"].strip()]
                body_size = sorted(sizes)[len(sizes) // 2] if sizes else 11
                for block in blocks:
                    for line in block.get("lines", []):
                        spans = line.get("spans", [])
                        text = "".join(span["text"] for span in spans).strip()
                        if not text:
                            continue
                        size = max(span["size"] for span in spans)
                        bold = any(span["flags"] & 16 for span in spans)
                        if size >= body_size * 1.6:
                            parts.append(f"\n# {text}\n")
                        elif size >= body_size * 1.25 or (bold and len(text) < 80 and size > body_size):
                            parts.append(f"\n## {text}\n")
                        else:
                            parts.append(text)
                    parts.append("")
                if token:
                    token.report((page_index + 1) / max(1, document.page_count))
        text = re.sub(r"\n{3,}", "\n\n", "\n".join(parts)).strip() + "\n"
        temp.write_text(text, encoding="utf-8")
    return atomic_write(destination, write, token)


def pdf_to_html(source: str | Path, *, policy: OutputPolicy | None = None,
                token: CancelToken | None = None) -> Path:
    """Export each PDF page as escaped, accessible XHTML text."""
    _require_pdf_backend()
    source = Path(source)
    destination = (policy or OutputPolicy()).destination(source, "html")
    def write(temp: Path):
        sections = []
        with fitz.open(source) as document:
            for index, page in enumerate(document, 1):
                if token:
                    token.check()
                content = page.get_text("text", sort=True)
                paragraphs = "".join(f"<p>{html.escape(line)}</p>" for line in content.splitlines() if line.strip())
                sections.append(f'<section aria-label="Page {index}">{paragraphs}</section>')
                if token:
                    token.report(index / max(1, document.page_count))
        result = ("<!doctype html><html><head><meta charset=\"utf-8\"><title>" +
                  html.escape(source.stem) + "</title></head><body>" + "".join(sections) + "</body></html>")
        temp.write_text(result, encoding="utf-8")
    return atomic_write(destination, write, token)


def pdf_to_docx(source: str | Path, *, policy: OutputPolicy | None = None,
                token: CancelToken | None = None) -> Path:
    """Create a flowing, editable Word document from the PDF's text blocks."""
    _require_pdf_backend()
    try:
        from docx import Document
        from docx.shared import Pt, RGBColor
    except ImportError as exc:
        raise ConversionError("DOCX export requires python-docx") from exc
    source = Path(source)
    destination = (policy or OutputPolicy(suffix=" flowing")).destination(source, "docx")
    def write(temp: Path):
        output = Document()
        output.core_properties.title = source.stem
        output.core_properties.author = "ConvertANNY"
        with fitz.open(source) as pdf:
            for page_index, page in enumerate(pdf):
                if token:
                    token.check()
                if page_index:
                    output.add_page_break()
                blocks = page.get_text("dict", sort=True)["blocks"]
                for block in blocks:
                    lines = block.get("lines", [])
                    spans = [span for line in lines for span in line.get("spans", [])]
                    if not spans:
                        continue
                    value = " ".join("".join(span["text"] for span in line.get("spans", [])).strip()
                                    for line in lines).strip()
                    if not value:
                        continue
                    paragraph = output.add_paragraph()
                    paragraph.paragraph_format.space_after = Pt(7)
                    for span in spans:
                        text = span["text"]
                        if not text:
                            continue
                        run = paragraph.add_run(text)
                        run.font.name = span.get("font", "Arial").split(",")[0]
                        run.font.size = Pt(max(6, min(72, span.get("size", 11))))
                        flags = span.get("flags", 0)
                        run.bold = bool(flags & 16)
                        run.italic = bool(flags & 2)
                        color = span.get("color", 0)
                        run.font.color.rgb = RGBColor((color >> 16) & 255, (color >> 8) & 255, color & 255)
                if token:
                    token.report((page_index + 1) / max(1, pdf.page_count))
        output.save(temp)
    return atomic_write(destination, write, token)


def pdf_to_docx_pages(source: str | Path, *, dpi: int = 180,
                      policy: OutputPolicy | None = None, token: CancelToken | None = None) -> Path:
    """Place a high-resolution page image on each Word page to retain PDF appearance."""
    _require_pdf_backend()
    try:
        from docx import Document
        from docx.enum.section import WD_SECTION
        from docx.shared import Inches
    except ImportError as exc:
        raise ConversionError("DOCX export requires python-docx") from exc
    source = Path(source)
    destination = (policy or OutputPolicy()).destination(source, "docx")
    def write(temp: Path):
        document = Document()
        with fitz.open(source) as pdf:
            for index, page in enumerate(pdf):
                if token:
                    token.check()
                rect = page.rect
                section = document.sections[0] if index == 0 else document.add_section(WD_SECTION.NEW_PAGE)
                section.page_width = Inches(rect.width / 72)
                section.page_height = Inches(rect.height / 72)
                section.top_margin = section.bottom_margin = Inches(0)
                section.left_margin = section.right_margin = Inches(0)
                image_data = page.get_pixmap(dpi=dpi, alpha=False).tobytes("png")
                paragraph = document.add_paragraph()
                paragraph.paragraph_format.space_after = Inches(0)
                paragraph.add_run().add_picture(__import__("io").BytesIO(image_data),
                                                width=Inches(rect.width / 72), height=Inches(rect.height / 72))
                if token:
                    token.report((index + 1) / max(1, pdf.page_count))
        document.core_properties.title = source.stem
        document.core_properties.author = "ConvertANNY"
        document.save(temp)
    return atomic_write(destination, write, token)


def pdf_to_xlsx(source: str | Path, *, policy: OutputPolicy | None = None,
                token: CancelToken | None = None) -> Path:
    """Extract vector/text tables into one worksheet per table."""
    _require_pdf_backend()
    try:
        from openpyxl import Workbook
    except ImportError as exc:
        raise ConversionError("XLSX export requires openpyxl") from exc
    source = Path(source)
    destination = (policy or OutputPolicy(suffix=" tables")).destination(source, "xlsx")

    def safe_sheet_name(page_number: int, table_number: int, used: set[str]) -> str:
        base = f"Page {page_number} Table {table_number}"
        base = re.sub(r"[\\/*?:\[\]]", " ", base).strip()[:31] or "Table"
        candidate = base
        number = 2
        while candidate.casefold() in used:
            suffix = f" {number}"
            candidate = base[:31-len(suffix)] + suffix
            number += 1
        used.add(candidate.casefold())
        return candidate

    def write(temporary: Path):
        workbook = Workbook()
        workbook.remove(workbook.active)
        used: set[str] = set()
        table_count = 0
        with fitz.open(source) as document:
            for page_index, page in enumerate(document, 1):
                if token:
                    token.check()
                try:
                    # The optional-layout advisory is printed by the backend on every page.
                    with redirect_stdout(io.StringIO()):
                        tables = page.find_tables().tables
                except Exception as exc:
                    raise ConversionError(f"Could not inspect tables on PDF page {page_index}: {exc}") from exc
                for table_index, table in enumerate(tables, 1):
                    if token:
                        token.check()
                    rows = table.extract()
                    if not rows:
                        continue
                    sheet = workbook.create_sheet(safe_sheet_name(page_index, table_index, used))
                    width = max((len(row) for row in rows if row), default=0)
                    for row_index, row in enumerate(rows, 1):
                        if token:
                            token.check()
                        for column_index in range(width):
                            value = row[column_index] if column_index < len(row) else None
                            if value is not None:
                                sheet.cell(row=row_index, column=column_index+1, value=str(value).strip())
                    sheet.freeze_panes = "A2" if len(rows) > 1 else "A1"
                    sheet.auto_filter.ref = sheet.dimensions
                    table_count += 1
                if token:
                    token.report(page_index / max(1, document.page_count))
        if not table_count:
            raise ConversionError("No extractable tables were found. Scanned pages need OCR before spreadsheet export.")
        workbook.save(temporary)
        workbook.close()

    return atomic_write(destination, write, token)


def rotate_pdf(source: str | Path, degrees: int, *, policy: OutputPolicy | None = None,
               token: CancelToken | None = None) -> Path:
    _require_pdf_backend()
    source = Path(source)
    degrees = int(degrees) % 360
    if degrees not in (0, 90, 180, 270):
        raise ConversionError("PDF rotation must be 0, 90, 180 or 270 degrees")
    destination = (policy or OutputPolicy(suffix="-rotated")).destination(source, "pdf")
    def write(temp: Path):
        with fitz.open(source) as doc:
            for index, page in enumerate(doc):
                if token:
                    token.check()
                page.set_rotation((page.rotation + degrees) % 360)
                if token:
                    token.report((index + 1) / max(1, doc.page_count))
            doc.save(temp, garbage=3, deflate=True)
    return atomic_write(destination, write, token)
