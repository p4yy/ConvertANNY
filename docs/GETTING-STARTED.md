# Getting started

## Install

1. Download the `ConvertANNY-Setup` installer from the [latest release](https://github.com/p4yy/ConvertANNY/releases/latest).
2. Run the installer and choose whether to add a desktop shortcut or File Explorer menu entry.
3. Open ConvertANNY from the Start menu or the shortcut you selected.

The installer is not code-signed, so Windows may identify its publisher as unknown. The release page includes SHA-256 checksums and a source archive.

To check the installer checksum in PowerShell, run `Get-FileHash .\ConvertANNY-Setup-<version>.exe -Algorithm SHA256` with the downloaded filename, then compare its `Hash` value with the matching entry in `SHA256SUMS.txt` from the same release.

## Convert a file

1. Add files or a folder to the workspace, or drag files into it.
2. Choose a conversion, tool or file action. While dragging in Explorer, the default shortcuts are **Shift** for conversions, **Ctrl** for tools and **Alt** for actions.
3. Follow the job in **Activity**. Results are saved beside the original unless you choose another destination.

The available operations depend on the selected files, codecs and installed helper applications. For example, Office document conversion requires Microsoft Office or LibreOffice, and RAR creation requires WinRAR. See [Features](FEATURES.md) for the full list and its requirements.

## Build from source

Building requires Windows and Python 3.12. From the repository folder, run:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\scripts\build.ps1
.\.venv\Scripts\python.exe scripts/package.py
```

The application bundle and installer are written to `dist/`. Build output, local environments and downloaded helper caches are excluded from Git.
