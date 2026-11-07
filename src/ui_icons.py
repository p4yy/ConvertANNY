"""Small, theme-aware ConvertANNY line icons rendered from owned SVG paths."""
from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


_PATHS = {
    "chevron_left": '<path d="m14.5 5-7 7 7 7"/>',
    "chevron_right": '<path d="m9.5 5 7 7-7 7"/>',
    "general": '<path d="M12 3.4v2M12 18.6v2M3.4 12h2m13.2 0h2M5.9 5.9l1.4 1.4m9.4 9.4 1.4 1.4m0-12.2-1.4 1.4m-9.4 9.4-1.4 1.4"/><circle cx="12" cy="12" r="6.2"/><circle cx="12" cy="12" r="2" fill="{accent}" stroke="none"/>',
    "wheel": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3"/><path d="M12 3v6m6.4-3.4-4.2 4.2M21 12h-6m3.4 6.4-4.2-4.2M12 21v-6m-6.4 3.4 4.2-4.2M3 12h6M5.6 5.6l4.2 4.2"/><circle cx="12" cy="12" r="1.3" fill="{accent}" stroke="none"/>',
    "sounds": '<path d="M5 16.5h14c-1.5-1.2-2-2.5-2-5.7a5 5 0 0 0-10 0c0 3.2-.5 4.5-2 5.7Z"/><path d="M10 19a2.2 2.2 0 0 0 4 0"/>',
    "files": '<path d="M3.5 7.2A1.7 1.7 0 0 1 5.2 5.5h5l2 2H19a1.7 1.7 0 0 1 1.7 1.7v8.1a1.7 1.7 0 0 1-1.7 1.7H5.2a1.7 1.7 0 0 1-1.7-1.7Z"/>',
    "float": '<rect x="3.5" y="4.5" width="17" height="14.5" rx="2.5"/><path d="m10 9 5 3-5 3Z" fill="{accent}" stroke="none"/>',
    "customize": '<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="9" cy="6" r="2" fill="{bg}"/><circle cx="15" cy="12" r="2" fill="{bg}"/><circle cx="11" cy="18" r="2" fill="{bg}"/><path d="M9 4a2 2 0 1 0 0 4 2 2 0 0 0 0-4Zm6 6a2 2 0 1 0 0 4 2 2 0 0 0 0-4Zm-4 6a2 2 0 1 0 0 4 2 2 0 0 0 0-4Z" fill="{accent}"/>',
    "advanced": '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="m7.5 9 3 3-3 3m5.5 0h4"/>',
    "about": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><circle cx="12" cy="7.5" r="1" fill="{accent}" stroke="none"/>',
    "quickshare": '<circle cx="6" cy="12" r="2.3"/><circle cx="18" cy="6" r="2.3"/><circle cx="18" cy="18" r="2.3"/><path d="m8.2 11 7.6-3.8m-7.6 5.8 7.6 3.8"/>',
    "link": '<path d="M9.5 14.5 14.5 9.5"/><path d="M7.7 15.8H6.5a4 4 0 0 1 0-8h4M16.3 8.2h1.2a4 4 0 0 1 0 8h-4"/>',
    "pclink": '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8m-4-4v4"/><circle cx="12" cy="10.5" r="3.5"/><path d="M8.5 10.5h7m-3.5-3.5c2 2 2 5 0 7m0-7c-2 2-2 5 0 7" stroke="{accent}"/>',
    "cloud": '<path d="M7 18.5h10a4 4 0 0 0 .2-8A5.5 5.5 0 0 0 6.8 9.3 4.6 4.6 0 0 0 7 18.5Z"/><path d="M12 11v6m-2.5-2.5L12 17l2.5-2.5" stroke="{accent}"/>',
    "bluetooth": '<path d="M8 8 16 16 12 20V4l4 4-8 8"/>',
    "wifi": '<path d="M3.5 9a13 13 0 0 1 17 0M6.8 12.5a8 8 0 0 1 10.4 0m-7.2 3.4a3.5 3.5 0 0 1 4.1 0"/><circle cx="12" cy="19" r="1" fill="{accent}"/>',
}


def _pixmap(kind: str, color: str, accent: str, background: str) -> QPixmap:
    shape = _PATHS.get(kind, _PATHS["about"]).format(accent=accent, bg=background)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24">'
           f'<g fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{shape}</g></svg>')
    image = QPixmap(48, 48)
    image.setDevicePixelRatio(2)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter)
    painter.end()
    return image


def navigation_icon(kind: str, *, normal: str, selected: str, accent: str, background: str) -> QIcon:
    icon = QIcon()
    icon.addPixmap(_pixmap(kind, normal, normal, background), QIcon.Normal)
    selected_pixmap = _pixmap(kind, selected, accent, background)
    icon.addPixmap(selected_pixmap, QIcon.Selected)
    icon.addPixmap(selected_pixmap, QIcon.Active)
    return icon
