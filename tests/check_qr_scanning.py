"""Read a generated QR image through the application scanning routes."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import segno
from PySide6.QtGui import QImage
import runtime
from convertanny_core.barcode_scan import scan_file
from PIL import Image


def main():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'qr.png'
        text = 'https://example.org/convertanny'
        segno.make(text, micro=False).save(path, scale=5, border=4)
        image = QImage(str(path))
        for codes in (runtime.find_codes(image), runtime.find_codes_in_file(path)):
            assert len(codes) == 1 and codes[0]['text'] == text
            assert codes[0]['kind'] == 'QR Code'
            bounds = codes[0]['rect']
            assert bounds.width() > 0 and bounds.height() > 0
            assert image.rect().contains(bounds.toRect())
        assert runtime.find_codes_in_file(Path(directory) / 'missing.png') == []
        blank = QImage(33, 31, QImage.Format_RGB32)
        blank.fill(0xffffffff)
        assert runtime.find_codes(blank) == []
        assert runtime.find_codes(QImage()) == []
        # Exercise the Pillow fallback even when Qt cannot load the named file.
        opened = []
        def load_fallback(_):
            opened.append(Image.open(path))
            return opened[-1]
        fallback = scan_file(Path(directory) / 'unknown.format', image_loader=load_fallback)
        assert fallback[0]['text'] == text
        assert opened[0].fp is None
    print('QR image scanning contracts passed')


if __name__ == '__main__':
    main()
