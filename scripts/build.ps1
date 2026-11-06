$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
& .\.venv\Scripts\python.exe scripts/assets.py
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --windowed --name ConvertANNY --icon src/assets/convertanny.ico --paths src --add-data 'src/assets;assets' --add-data 'licenses;licenses' --add-data 'LICENSE;.' --add-data 'NOTICE;.' --collect-all imageio_ffmpeg --collect-all pillow_heif --collect-binaries onnxruntime --hidden-import win32timezone --hidden-import win32com.shell.shell --hidden-import PySide6.QtMultimedia --collect-submodules locales --hidden-import fontTools.ttLib --hidden-import brotli --exclude-module tkinter --exclude-module matplotlib --exclude-module sympy src/convertanny.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
