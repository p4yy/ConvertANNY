"""Paginate HTML into PDF with ConvertANNY's document styling."""

from __future__ import annotations

from pathlib import Path

from .paths import atomic_write


HTML_DOCUMENT_CSS = """
body{font-family:'Segoe UI',Helvetica,Arial,sans-serif;font-size:11pt;line-height:1.5;color:#1d1d1f}
h1{font-size:22pt}h2{font-size:17pt}h3{font-size:13pt}
code,pre{font-family:Consolas,monospace;font-size:9.5pt;background:#f3f3f3}
pre{padding:6px}table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:3px 6px}
blockquote{color:#555;margin-left:12px}
"""


def html_to_pdf(html_body: str, output: str | Path) -> Path:
    """Render an HTML body on A4 pages with 54-point margins."""
    import pymupdf

    output = Path(output)

    def render(temporary: Path) -> None:
        story = pymupdf.Story(html=html_body, user_css=HTML_DOCUMENT_CSS)
        writer = pymupdf.DocumentWriter(str(temporary))
        media_box = pymupdf.paper_rect("a4")
        content_box = media_box + (54, 54, -54, -54)
        try:
            more = True
            while more:
                device = writer.begin_page(media_box)
                more, _ = story.place(content_box)
                story.draw(device)
                writer.end_page()
        finally:
            writer.close()

    return atomic_write(output, render)
