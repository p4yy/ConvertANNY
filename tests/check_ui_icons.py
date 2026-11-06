"""Render every ConvertANNY line icon at high DPI and check it has visible pixels."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QSize
from PySide6.QtGui import QGuiApplication, QIcon
from ui_icons import _PATHS, navigation_icon


def check():
    app = QGuiApplication.instance() or QGuiApplication([])
    for name in _PATHS:
        icon = navigation_icon(name, normal="#64786c", selected="#16241d",
                               accent="#2563eb", background="#f5f7f3")
        for mode in (QIcon.Normal, QIcon.Selected):
            image = icon.pixmap(QSize(52, 52), mode).toImage()
            assert not image.isNull(), name
            visible = sum(1 for y in range(image.height()) for x in range(image.width())
                          if image.pixelColor(x, y).alpha() > 0)
            assert visible > 80, f"{name} rendered too faintly ({visible} pixels)"
    print(f"{len(_PATHS)} original line icons rendered at 2× for normal and selected states")
    del app


if __name__ == "__main__":
    check()
