"""Consistent static Inter faces for widgets, menus and painted UI."""
from pathlib import Path
from PySide6.QtGui import QFont, QFontDatabase

FAMILY = 'ConvertANNY UI'


def install(application):
    folder = Path(__file__).resolve().parent / 'assets' / 'fonts'
    # Static faces avoid variable-axis selection differences across Windows/Qt versions.
    for name in ('Regular', 'Medium', 'SemiBold', 'Bold'):
        path = folder / f'ConvertANNYInter-{name}.ttf'
        if QFontDatabase.addApplicationFont(str(path)) < 0:
            raise RuntimeError(f'Unable to load interface font: {path.name}')
    application.setFont(ui_font())


def ui_font(points=10, weight=QFont.Normal):
    font = QFont(FAMILY, points, weight)
    font.setStyleStrategy(QFont.PreferAntialias)
    font.setHintingPreference(QFont.PreferFullHinting)
    return font
