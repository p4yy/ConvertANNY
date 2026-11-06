"""Face decoding checks using synthetic network output (the model file is not needed)."""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import engine
from convertanny_core import faces


class _Name:
    def __init__(self, name):
        self.name = name


class FakeSession:
    """Fixed outputs for a 128x96 canvas: two faces, one of them seen by two strides."""
    W, H = 128, 96

    def __init__(self):
        rng = np.random.default_rng(7)
        self.out = {}
        for st in (8, 16, 32):
            n = (self.W // st) * (self.H // st)
            self.out[f"cls_{st}"] = rng.uniform(0, 0.3, (1, n, 1)).astype(np.float32)
            self.out[f"obj_{st}"] = rng.uniform(0, 0.3, (1, n, 1)).astype(np.float32)
            box = rng.uniform(-0.5, 0.5, (1, n, 4)).astype(np.float32)
            box[..., 2:] = rng.uniform(0.2, 0.9, (1, n, 2))
            self.out[f"bbox_{st}"] = box
            self.out[f"kps_{st}"] = np.zeros((1, n, 10), np.float32)

        def put(st, r, c, score, box):
            i = r * (self.W // st) + c
            self.out[f"cls_{st}"][0, i, 0] = score
            self.out[f"obj_{st}"][0, i, 0] = score
            self.out[f"bbox_{st}"][0, i] = box

        put(8, 4, 5, 0.95, [0.1, 0.0, np.log(3.0), np.log(3.5)])
        put(16, 2, 2, 0.80, [0.3, 0.4, np.log(1.6), np.log(1.8)])
        put(16, 4, 6, 0.90, [0.0, 0.0, np.log(1.5), np.log(1.5)])
        put(32, 1, 3, 0.70, [0.2, 0.2, np.log(1.0), np.log(1.2)])

    def get_outputs(self):
        return [_Name(n) for n in self.out]

    def get_inputs(self):
        return [_Name("input")]

    def run(self, _names, feed):
        tensor = feed["input"]
        assert tensor.shape == (1, 3, self.H, self.W) and tensor.dtype == np.float32
        return list(self.out.values())


def _rounded(found):
    return [tuple(round(v, 3) for v in f) for f in found]


def check_input_is_padded_bgr():
    img = Image.new("RGB", (33, 20), (10, 20, 30))
    tensor, pw, ph = faces.prepare_input(img)
    assert (pw, ph) == (64, 32) and tensor.shape == (1, 3, 32, 64)
    assert list(tensor[0, :, 0, 0]) == [30.0, 20.0, 10.0]          # blue first
    assert tensor[0, :, 25, 40].sum() == 0                           # padding is black
    exact, w, h = faces.prepare_input(Image.new("L", (64, 32)))
    assert (w, h) == (64, 32) and exact.shape == (1, 3, 32, 64)


def check_decode_and_merge_across_strides():
    engine._YUNET = FakeSession()
    img = Image.new("RGB", (100, 70), (200, 100, 50))
    got = _rounded(engine.detect_faces(img))
    assert got == [(28.8, 18.0, 24.0, 28.0, 0.95), (84.0, 52.0, 24.0, 24.0, 0.9), (86.4, 19.2, 32.0, 38.4, 0.7)], got


def check_thresholds():
    engine._YUNET = FakeSession()
    img = Image.new("RGB", (100, 70))
    assert engine.detect_faces(img, score_thr=0.99) == []
    loose = _rounded(engine.detect_faces(img, nms_thr=0.9))
    assert (24.0, 24.0, 25.6, 28.8, 0.8) in loose and len(loose) == 4, loose
    scores = [f[4] for f in engine.detect_faces(img)]
    assert scores == sorted(scores, reverse=True)


def check_suppression_directly():
    boxes = np.array([[0, 0, 10, 10], [1, 1, 10, 10], [50, 50, 5, 5]], dtype=float)
    assert faces.suppress_overlaps(boxes, np.array([0.5, 0.9, 0.4]), 0.3) == [1, 2]
    assert faces.suppress_overlaps(boxes, np.array([0.5, 0.9, 0.4]), 0.99) == [1, 0, 2]
    assert faces.suppress_overlaps(np.zeros((0, 4)), np.zeros(0), 0.3) == []


def check_face_centre_from_video():
    import subprocess, tempfile
    with tempfile.TemporaryDirectory() as d:
        clip = Path(d) / "c.mp4"
        subprocess.run([engine.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        "testsrc=size=320x240:rate=10:duration=2", "-pix_fmt", "yuv420p", str(clip)], check=True)
        saved = engine.detect_faces
        try:
            engine.detect_faces = lambda frame, *a: [(100.0, 10.0, 40.0, 40.0, 0.9)]
            assert abs(engine._face_center_x(str(clip)) - 120 / 640) < 1e-9
            engine.detect_faces = lambda frame, *a: []
            assert engine._face_center_x(str(clip)) is None
            engine.detect_faces = lambda frame, *a: 1 / 0
            assert engine._face_center_x(str(clip)) is None
        finally:
            engine.detect_faces = saved
    assert engine._face_center_x("/no/such/file.mp4") is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("check_") and callable(fn):
            fn()
    print("Engine face detection decoding passed")
