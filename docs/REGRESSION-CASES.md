# Conversion regression cases

User-provided issue screenshots dated 2026-11-05 are quality references, not evidence that every issue occurs in ConvertANNY. Format requests in those screenshots do not establish supported conversion formats.

## Confirmed fixes

- Animated GIF/WebP to AVIF: preserve three distinct test frames and their 80/160/240 ms durations. Previously, the owned image path flattened AVIF output.
- PDF merge: retain bookmarks with updated page destinations. Tests also confirm existing form values and internal page links after merging two two-page documents.

Run `.venv/Scripts/python.exe tests/check_screenshot_regressions.py` from the workspace.

## Still requiring release checks

- DOCX to PDF: headers, spacing, fonts, pagination and tables using the installed Office/LibreOffice backend.
- PDF to DOCX: distinguish page-faithful output from flowing editable output; verify nonblank pages and expected layout.
- Arabic and Persian text: reading order, shaping, encodings and embedded font coverage.
- Spreadsheet pagination and complete image placement.
- Batch/watch-folder conversion: full output count, source retention and meaningful partial-failure reporting.
- Browser image save: one output for one action.
- Tooltips, idle resource use and installer success/error paths.
- Named PDF destinations and complex forms beyond the simple internal links and text fields in the current regression.

These items are not marked fixed merely because an unrelated test passes.

## Office backend status

The Office orchestration was replaced and its dispatch/output handling checked. Real Word/LibreOffice rendering could not be checked because neither backend was detected. The DOCX layout/header issues remain open.

API references: [Microsoft Word fixed-format export](https://learn.microsoft.com/en-us/office/vba/api/word.document.exportasfixedformat), [LibreOffice command-line parameters](https://help.libreoffice.org/latest/en-GB/text/shared/guide/start_parameters.html).
