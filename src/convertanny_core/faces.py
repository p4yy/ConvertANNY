"""Face boxes from a YuNet-style detector run through onnxruntime.

The network emits, for each of three strides, a class score, an objectness score and a box
encoded relative to its grid cell. This module turns those tensors into pixel boxes and removes
duplicates. The decoding and suppression steps are plain numpy so they can be tested with
synthetic tensors, without the model file.
"""
from __future__ import annotations

import numpy as np

STRIDES = (8, 16, 32)
_MULTIPLE = 32          # the network wants both sides to be a multiple of this


def open_session(model_path):
    import onnxruntime as ort
    options = ort.SessionOptions()
    options.log_severity_level = 3
    return ort.InferenceSession(str(model_path), options, providers=["CPUExecutionProvider"])


def prepare_input(rgb) -> tuple[np.ndarray, int, int]:
    """A PIL image as the network's input: BGR floats 0-255, zero-padded up to multiples of 32.
    Returns (tensor of shape 1x3xHxW, padded width, padded height)."""
    rgb = rgb.convert("RGB")
    width, height = rgb.size
    padded_w = -(-width // _MULTIPLE) * _MULTIPLE
    padded_h = -(-height // _MULTIPLE) * _MULTIPLE
    canvas = np.zeros((padded_h, padded_w, 3), dtype=np.float32)
    canvas[:height, :width] = np.asarray(rgb, dtype=np.float32)[..., ::-1]
    return np.moveaxis(canvas, 2, 0)[np.newaxis], padded_w, padded_h


def decode_stride(outputs: dict, stride: int, padded_w: int, floor: float):
    """Boxes (x, y, w, h) and scores for the cells of one stride whose score reaches `floor`."""
    cls = np.clip(outputs[f"cls_{stride}"][0, :, 0], 0.0, 1.0)
    obj = np.clip(outputs[f"obj_{stride}"][0, :, 0], 0.0, 1.0)
    score = np.sqrt(cls * obj)
    cells = np.flatnonzero(score >= floor)
    if cells.size == 0:
        return None
    raw = outputs[f"bbox_{stride}"][0][cells]
    row, col = np.divmod(cells, padded_w // stride)
    centre_x = (col + raw[:, 0]) * stride
    centre_y = (row + raw[:, 1]) * stride
    size = np.exp(raw[:, 2:4]) * stride
    boxes = np.column_stack([centre_x - size[:, 0] / 2, centre_y - size[:, 1] / 2, size[:, 0], size[:, 1]])
    return boxes, score[cells]


def suppress_overlaps(boxes: np.ndarray, scores: np.ndarray, overlap: float) -> list[int]:
    """Indices to keep, best score first, dropping boxes whose overlap with a kept one exceeds `overlap`."""
    left, top = boxes[:, 0], boxes[:, 1]
    right, bottom = left + boxes[:, 2], top + boxes[:, 3]
    area = boxes[:, 2] * boxes[:, 3]
    waiting = np.argsort(-scores, kind="stable")
    kept: list[int] = []
    while waiting.size:
        best, waiting = int(waiting[0]), waiting[1:]
        kept.append(best)
        if not waiting.size:
            break
        width = np.clip(np.minimum(right[best], right[waiting]) - np.maximum(left[best], left[waiting]), 0, None)
        height = np.clip(np.minimum(bottom[best], bottom[waiting]) - np.maximum(top[best], top[waiting]), 0, None)
        shared = width * height
        ratio = shared / (area[best] + area[waiting] - shared + 1e-9)
        waiting = waiting[ratio <= overlap]
    return kept


def detect(session, rgb, floor: float = 0.6, overlap: float = 0.3) -> list[tuple[float, float, float, float, float]]:
    """Faces in a PIL image as (x, y, w, h, score)."""
    tensor, padded_w, _padded_h = prepare_input(rgb)
    names = [o.name for o in session.get_outputs()]
    outputs = dict(zip(names, session.run(None, {session.get_inputs()[0].name: tensor})))
    found = [d for d in (decode_stride(outputs, s, padded_w, floor) for s in STRIDES) if d is not None]
    if not found:
        return []
    boxes = np.concatenate([b for b, _ in found])
    scores = np.concatenate([s for _, s in found])
    return [(*map(float, boxes[i]), float(scores[i])) for i in suppress_overlaps(boxes, scores, overlap)]
