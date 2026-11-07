$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$Python = Join-Path (Get-Location) '.venv\Scripts\python.exe'
if (!(Test-Path $Python)) { $Python = Join-Path (Get-Location) '.build-tools\python312\python.exe' }
if (!(Test-Path $Python)) { throw 'Python 3.12 build environment not found. Follow docs/GETTING-STARTED.md.' }
& $Python scripts/assets.py
if ($LASTEXITCODE -ne 0) { throw 'Asset preparation failed' }
& $Python -m PyInstaller --noconfirm --windowed --name ConvertANNY --icon src/assets/convertanny.ico --paths src --add-data 'src/assets;assets' --add-data 'licenses;licenses' --add-data 'LICENSE;.' --add-data 'NOTICE;.' --add-data 'VERSION;.' --collect-all imageio_ffmpeg --collect-all pillow_heif --collect-binaries onnxruntime --hidden-import win32timezone --hidden-import win32com.shell.shell --hidden-import PySide6.QtMultimedia --collect-submodules locales --hidden-import fontTools.ttLib --hidden-import brotli --exclude-module tkinter --exclude-module matplotlib --exclude-module sympy src/convertanny.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
