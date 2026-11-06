"""Face-blur checks with a stand-in detector: boxes are scaled back, padded, clipped, and only the faces change."""
import hashlib
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image
import PIL

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import engine
from convertanny_core import face_blur

PINNED_PILLOW = '13.0.0'
PINNED = {"rgb": ["rgb blurred.png", "RGB", [200, 150], "4d2c64527909a353"], "rgba": ["rgba blurred.png", "RGBA", [200, 150], "2a4f91d097c39e61"], "big": ["big blurred.png", "RGB", [3200, 1800], "a53e6263a83e777f"]}


def noise(size, mode):
    rng = np.random.default_rng(3)
    channels = {"RGB": 3, "RGBA": 4}[mode]
    return Image.fromarray(rng.integers(0, 256, (size[1], size[0], channels), dtype=np.uint8), mode)


def digest(path):
    im = Image.open(path)
    return [im.mode, list(im.size), hashlib.sha256(im.tobytes()).hexdigest()[:16]]


def fake_faces(seen):
    def detect(img, *rest):
        seen.append(list(img.size))
        w, h = img.size
        return [(w * 0.3, h * 0.25, w * 0.25, h * 0.3, 0.9), (w * 0.8, h * 0.7, w * 0.3, h * 0.5, 0.8)]
    return detect


def check_blur_properties():
    seen = []
    saved = engine.detect_faces
    engine.detect_faces = fake_faces(seen)
    try:
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            src = d / "pic.png"
            original = noise((200, 150), "RGB")
            original.save(src)
            out = engine.image_blur_faces(str(src), {})
            assert out.name == "pic blurred.png" and seen == [[200, 150]]
            before, after = np.asarray(original, dtype=int), np.asarray(Image.open(out), dtype=int)
            assert (before[:10] == after[:10]).all()                      # far from any face: untouched
            face = (slice(40, 70), slice(70, 100))
            assert after[face].std() < before[face].std() / 2             # inside the face: smoothed
            assert Image.open(out).size == (200, 150)
            rgba = d / "alpha.png"
            noise((200, 150), "RGBA").save(rgba)
            assert Image.open(engine.image_blur_faces(str(rgba), {})).mode == "RGBA"
            big = d / "big.png"
            noise((3200, 1800), "RGB").save(big)
            seen.clear()
            engine.image_blur_faces(str(big), {})
            assert seen == [[1600, 900]]                                   # detection ran on a smaller copy
            jpg = d / "j.jpg"
            noise((120, 90), "RGB").save(jpg)
            assert engine.image_blur_faces(str(jpg), {}).name == "j blurred.jpg"
            engine.detect_faces = lambda img, *rest: []
            try:
                engine.image_blur_faces(str(src), {})
            except engine.ConversionError as exc:
                assert str(exc) == "No faces found in this image"
            else:
                raise AssertionError("expected an error")
    finally:
        engine.detect_faces = saved


def check_pixels_match_recorded_output():
    if PIL.__version__.split(".")[0] != PINNED_PILLOW.split(".")[0]:
        return                                                            # blur kernels may differ between major versions
    saved = engine.detect_faces
    engine.detect_faces = fake_faces([])
    try:
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            for name, size, mode in (("rgb", (200, 150), "RGB"), ("rgba", (200, 150), "RGBA"), ("big", (3200, 1800), "RGB")):
                src = d / (name + ".png")
                noise(size, mode).save(src)
                out = engine.image_blur_faces(str(src), {})
                assert [out.name] + digest(out) == PINNED[name], name
    finally:
        engine.detect_faces = saved


def check_geometry_helpers():
    assert face_blur.detection_scale((800, 600)) == 1.0
    assert face_blur.detection_scale((3200, 1000)) == 0.5
    rect = face_blur.face_rectangle((10, 10, 50, 50, 0.9), 1.0, (100, 100))
    assert rect == (1, 1, 69, 69), rect
    clipped = face_blur.face_rectangle((90, 90, 50, 50, 0.9), 1.0, (100, 100))
    assert clipped == (81, 81, 100, 100), clipped
    scaled = face_blur.face_rectangle((10, 10, 20, 20, 0.9), 0.5, (400, 400))
    assert scaled == (12, 12, 67, 67), scaled


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("check_") and callable(fn):
            fn()
    print("Engine face blur passed")
