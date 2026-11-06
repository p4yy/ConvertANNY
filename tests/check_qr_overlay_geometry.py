"""High-DPI QR overlay coordinates map between source pixels and screen points."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PySide6.QtCore import QRectF, QPointF
from convertanny_core.qr_overlay_geometry import screen_rect, source_rect, hit_test


def main():
    pixels = QRectF(100, 60, 80, 40)
    view = screen_rect(pixels, 2)
    assert view == QRectF(42, 22, 56, 36)
    assert source_rect(view, 2) == QRectF(84, 44, 112, 72)
    codes = [{'view': view}, {'view': QRectF(200, 200, 10, 10)}]
    assert hit_test(codes, QPointF(50, 30)) == 0
    assert hit_test(codes, QPointF(199, 199)) is None
    assert hit_test([], QPointF(1, 1)) is None
    print('QR overlay geometry passed')


if __name__ == '__main__': main()
