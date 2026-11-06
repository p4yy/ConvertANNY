"""Soft oval blur over detected faces."""
from __future__ import annotations

from typing import Iterable, Sequence

from PIL import Image, ImageDraw, ImageFilter

PADDING = 0.18             # grow each detected box by this fraction of its size on every side
DETECT_LONG_SIDE = 1600    # detection runs on a copy no larger than this


def detection_scale(size: tuple[int, int]) -> float:
    """How much to shrink an image of `size` before detection (1.0 = not at all)."""
    return min(1.0, DETECT_LONG_SIDE / max(size))


def shrink_for_detection(picture: Image.Image) -> tuple[Image.Image, float]:
    scale = detection_scale(picture.size)
    if scale >= 1:
        return picture, scale
    return picture.resize((max(1, int(picture.width * scale)), max(1, int(picture.height * scale))),
                          Image.LANCZOS), scale


def face_rectangle(face: Sequence[float], scale: float, limits: tuple[int, int]) -> tuple[int, int, int, int]:
    """Pixel rectangle (left, top, right, bottom) for a face found on the shrunken copy, padded and kept on the image."""
    x, y, w, h = (float(v) / scale for v in face[:4])
    return (int(max(0, x - w * PADDING)), int(max(0, y - h * PADDING)),
            int(min(limits[0], x + w * (1 + PADDING))), int(min(limits[1], y + h * (1 + PADDING))))


def oval_mask(size: tuple[int, int], feather: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size[0] - 1, size[1] - 1], fill=255)
    return mask.filter(ImageFilter.GaussianBlur(feather))


def blur_faces(canvas: Image.Image, faces: Iterable[Sequence[float]], scale: float) -> Image.Image:
    """Blur an oval over each face, in place, and return the canvas."""
    for face in faces:
        box = face_rectangle(face, scale, canvas.size)
        patch = canvas.crop(box)
        strength = max(6, int(max(patch.size) / 6))
        canvas.paste(patch.filter(ImageFilter.GaussianBlur(strength)), box[:2],
                     oval_mask(patch.size, max(2, strength // 3)))
    return canvas
