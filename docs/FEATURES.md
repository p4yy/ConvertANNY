# ConvertANNY features

Operations appear according to the selected files. Available formats also depend on installed codecs, helper applications and optional models.

## Workspace and orbit

- Add files, select a folder or drop files into the workspace.
- Search conversion formats, tools and file actions.
- Open the orbit while dragging a file: Shift for conversions, Ctrl for tools and Alt for actions by default.
- Customize shortcuts, including supported mouse-button combinations.
- Choose drag, hover or Explorer-selection triggers.
- Open the orbit through optional File Explorer context-menu and Send To entries.
- Configure mouse-shake and scroll-wheel gestures.
- Preview files with a configurable shortcut, either held or toggled.
- Select orbit segments with the keyboard, confirm with Enter and cancel with Escape.
- Save clipboard images to a selected output folder and choose a conversion.
- Read QR codes in image files or from a screen capture.

## Conversion formats

Targets are shown when compatible with the current selection. A listed target is not a promise that every source format can convert to it.

| Category | Output formats and routes |
| --- | --- |
| Images | PNG, JPG/JPEG, WebP, HEIC, AVIF, TIFF, BMP, GIF, ICO, TGA, JPEG 2000, ICNS and PDF |
| Video | MP4, MOV, MKV, WebM, AVI and WMV; H.264/H.265 options; GIF export; MP3/M4A audio extraction |
| Audio | MP3, M4A, WAV, FLAC, OGG, Opus, AIFF, WMA and AC3 |
| PDF | DOCX page-layout and flowing-text routes; XLSX table extraction; PNG/JPG pages; text, Markdown, HTML and CBZ |
| Text and documents | TXT, Markdown and HTML to PDF; a Markdown-rendering option for TXT; HTML/Markdown/text interchange; DOCX output where available |
| Office documents | PDF, DOCX, DOC, ODT, RTF, TXT and HTML through an installed Office backend |
| Presentations | PDF, PNG/JPG slide images, PPTX, PPT and ODP through an installed Office backend |
| Spreadsheets | XLSX, CSV, TSV, JSON, HTML, Markdown and PDF; XLS/ODS through an installed Office backend |
| Subtitles | SRT, VTT, ASS and plain text |
| Archives | ZIP, 7Z, TAR, TAR.GZ, TAR.BZ2 and TAR.XZ; RAR creation through WinRAR; GZIP for individual files |
| E-books | PDF, text, Markdown and HTML for supported readable inputs; PNG/JPG page export for XPS/OXPS |
| Comics | PDF, CBZ and page extraction for supported comic archives |
| Fonts | TTF, WOFF, WOFF2 and supported OTF routes; direct TTF-to-OTF conversion is excluded |

## Image tools

- Compress images and choose output-size presets.
- Crop, resize, rotate, flip, sharpen and convert to grayscale.
- Correct document perspective and alignment with scan controls.
- Strip metadata, upscale by 2×, add text watermarks and blur detected faces.
- Remove backgrounds with the optional local background-removal model.
- Extract image text using Windows OCR.
- Combine images into a PDF, stitch them horizontally or vertically, create a timed GIF or build a CBZ comic.

## PDF tools

- Compress, merge, split and rotate PDFs.
- Extract selected pages or embedded images.
- Arrange, reorder, rotate, insert and remove pages with the page editor.
- Add page numbers with position and style controls.
- Apply text or image watermarks and place signatures.
- Password-protect PDFs or unlock them with the required password.
- Convert to grayscale and count words.
- Combine compatible PDF/image selections, including image signatures and logo watermarks.

PDF-to-XLSX extracts detectable tables; scanned pages do not automatically become structured spreadsheets. DOCX conversion has separate page-layout and flowing-text routes, with different editing and layout tradeoffs.

## Audio, video and subtitles

| Video | Audio |
| --- | --- |
| Compress to a target size and resize to 720p | Compress, trim and merge |
| Trim, merge, mute, rotate and export a frame | Normalize levels, convert to mono and apply fades |
| Double playback speed or crop to social aspect ratios | Create iPhone M4R or Android MP3 ringtones |
| Create a GIF from a selected clip | Transcribe speech with the optional local model |
| Extract audio as MP3 or M4A | Detect language, choose Arabic/English or translate speech to English |

Subtitle tools can burn supported sidecar subtitles into video, add subtitle tracks to MKV, extract embedded text subtitle tracks to SRT and convert subtitle files between supported formats.

## File and archive tools

- Copy files or paths to the clipboard, copy/move to another folder, reveal results in Explorer, open a terminal or choose another application.
- Batch rename with replacement text, numbering, padding, dates, letter case and numeral conversion.
- Calculate SHA-256 checksums.
- Create and extract supported archives or repack an archive into another format.
- Create AES-256 ZIP or 7Z archives; 7Z can also hide archive filenames.
- Split large files into parts and join part files.
- Install supported fonts for the current user.
- Repair supported Arabic text-encoding problems and count words in readable documents.
- Unblock downloaded files through Windows integration.
- Use the confirmed overwrite-and-delete action when needed. Recoverability depends on the filesystem and storage hardware.

## Floating player and preview

- Open pictures, readable document previews, music, video or an empty drop window.
- Keep a window on top, resize it, hide its name or border and choose taskbar visibility.
- Control playback, seeking, volume, rate and repeat behavior.
- Use supported sidecar or embedded subtitles.
- Play supported copied media links with the optional link helper.
- Save links, reopen recent media and restore pinned window positions and playback state.
- Control a media float using keyboard media keys and optional on-screen media indicators.

## Sharing

- Transfer selected files or folders to a phone on the same network using a QR link served by the PC.
- Offer folder downloads and a combined ZIP download.
- Create an optional temporary PC-hosted internet link through Cloudflare.
- Use optional temporary upload services or supported configured cloud folders.
- Hand files to installed Quick Share or Windows Bluetooth tools.
- Copy links, display QR codes and reopen active sharing windows.

Online routes use the selected provider and require a working connection. A PC-hosted link requires the sharing window or retained sharing session to remain active; network and firewall configuration can affect access.

## Jobs, automation and output

- Run conversion jobs in background processes with progress and cancellation.
- Queue jobs or allow them to run in parallel.
- Review completed and failed jobs in Activity, then open or reveal available results.
- Save results beside the original, to a chosen folder or to the clipboard where supported.
- Choose replacement output explicitly; replacement prompts and applicable undo actions depend on the operation.
- Create watched-folder rules for automatic conversions.
- Save image/video presets and chain compatible operations.
- Add custom application actions and choose which orbit segments appear and in what order.

## Preferences and Windows integration

- Light, dark, system and high-contrast appearance choices.
- English, Arabic, French, Spanish, Turkish and German interface options.
- Configurable orbit opening/closing animations, animation speed and gesture behavior.
- Optional wheel sounds, completion sounds and completion animation, with volume and sound-pack controls.
- Optional startup at sign-in, Explorer context-menu integration and Send To entries.
- Settings export/import, default restoration, the usage guide and local logs.
- Optional crash-report prompts and update checks against a configured ConvertANNY release repository.
- A current-user installer with optional Explorer integration and Desktop shortcut, plus an uninstaller.

## Command line

```powershell
ConvertANNY.exe list "photo.png"
ConvertANNY.exe convert "photo.png" --to webp
ConvertANNY.exe convert "report.txt" --to pdf --out "D:\Converted"
```

Use `tool <operation-id> <files>` for an unattended tool. `list` shows the available IDs for a selection. Repeat `--set NAME=VALUE` to supply parameters; operations that need an interactive editor belong in the desktop app.

## Requirements by feature

| Feature | Requirement |
| --- | --- |
| Office document, presentation and some spreadsheet routes | Microsoft Office or LibreOffice installed locally |
| RAR creation | WinRAR |
| Some archive extraction routes | A compatible installed extraction utility |
| Image OCR | Windows OCR support and the appropriate recognition language |
| Background removal and transcription | Optional downloaded models; processing runs locally once available |
| Link playback and PC-hosted internet links | Downloadable helper executables and network access |
| Quick Share and Bluetooth transfer | Installed/configured Windows sharing tools and compatible devices |
| Updates | A configured release repository with a compatible published installer |

Conversion quality and available output formats depend on the input, codec support and selected backend. Fonts, document layout and animation handling can vary between formats.
