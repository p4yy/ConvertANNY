# Third-party components

ConvertANNY uses third-party software under its authors' license terms. The
application license does not replace those terms. The installer includes
component notices in `_internal/licenses/components` and application source in
`Source`. The public repository and each release also provide application
source and build scripts.

`requirements.txt` lists direct dependencies. `requirements-release.txt` records
the Python packages present in the release build environment; it includes build
tools as well as runtime dependencies.

Notable components and upstream source:

| Component | License / upstream source |
| --- | --- |
| PyMuPDF / MuPDF | AGPLv3 or a separate commercial license; this release uses the AGPL route. [PyMuPDF](https://github.com/pymupdf/PyMuPDF), [MuPDF](https://github.com/ArtifexSoftware/mupdf) |
| PySide6 / Qt | LGPLv3/GPL/commercial terms as applicable to each module. [PySide](https://code.qt.io/pyside/pyside-setup.git/), [Qt](https://code.qt.io/qt/) |
| FFmpeg through imageio-ffmpeg | The bundled build's terms apply. [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg), [FFmpeg](https://ffmpeg.org/download.html) |
| Inter font | SIL Open Font License 1.1; see `licenses/Inter-OFL.txt`. [Source](https://github.com/rsms/inter) |

Preserve component notices when redistributing. Qt libraries are dynamically
loaded from the installed bundle; the application license does not prohibit
replacing LGPL libraries or reverse engineering for debugging modifications to
those libraries. Downloaded optional tools and models carry their own upstream
terms and are not relicensed as ConvertANNY code.

