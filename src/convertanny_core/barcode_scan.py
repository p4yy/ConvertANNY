"""Barcode decoding for Qt images and local files."""
from contextlib import ExitStack
from io import BytesIO


def scan_image(image):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage
    import numpy
    import zxingcpp

    if image.isNull():
        return []
    grayscale = image.convertToFormat(QImage.Format_Grayscale8)
    # Qt aligns rows; expose only the visible pixels to the decoder.
    pixels = numpy.ndarray((grayscale.height(), grayscale.width()), dtype=numpy.uint8,
                           buffer=grayscale.constBits(), strides=(grayscale.bytesPerLine(), 1))
    results = []
    for barcode in zxingcpp.read_barcodes(pixels.copy()):
        if barcode.text:
            polygon = barcode.position
            corners = (polygon.top_left, polygon.top_right, polygon.bottom_left, polygon.bottom_right)
            left = min(point.x for point in corners)
            top = min(point.y for point in corners)
            bounds = QRectF(left, top, max(point.x for point in corners) - left,
                           max(point.y for point in corners) - top)
            results.append(dict(text=barcode.text, kind=str(barcode.format), rect=bounds))
    return results


def scan_file(path, *, image_loader, decoder=scan_image):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage

    image = QImage(str(path))
    if image.isNull():
        try:
            with ExitStack() as resources:
                original = image_loader(path)
                resources.callback(original.close)
                rgb = original.convert('RGB')
                if rgb is not original:
                    resources.callback(rgb.close)
                buffer = BytesIO()
                rgb.save(buffer, format='PNG')
                image = QImage.fromData(buffer.getvalue())
        except Exception:
            return []
    results = decoder(image)
    if results or max(image.width(), image.height()) >= 1600:
        return results
    enlarged = image.scaled(image.size() * 2, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return decoder(enlarged)
