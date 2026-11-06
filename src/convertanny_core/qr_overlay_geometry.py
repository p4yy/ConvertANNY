"""Coordinate transforms shared by the QR selection overlay."""
from PySide6.QtCore import QPointF, QRectF


def screen_rect(pixel_rect, device_ratio, inset=8):
    ratio = device_ratio or 1.0
    return QRectF(pixel_rect.x() / ratio, pixel_rect.y() / ratio,
                  pixel_rect.width() / ratio, pixel_rect.height() / ratio).adjusted(-inset, -inset, inset, inset)


def source_rect(view_rect, device_ratio):
    return QRectF(view_rect.x() * device_ratio, view_rect.y() * device_ratio,
                  view_rect.width() * device_ratio, view_rect.height() * device_ratio)


def hit_test(codes, position):
    point = QPointF(position)
    return next((index for index, code in enumerate(codes) if code['view'].contains(point)), None)
