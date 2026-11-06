"""Local, cancellable subject masking through the configured ONNX model."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops

from .model import CancelToken, ConversionError


_SESSIONS = {}


def _session(model: Path):
    model = Path(model).resolve()
    session = _SESSIONS.get(model)
    if session is None:
        if not model.is_file():
            raise ConversionError("The background removal model is not available")
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise ConversionError("Background removal requires the bundled ONNX runtime") from exc
        options = ort.SessionOptions()
        options.log_severity_level = 3
        session = ort.InferenceSession(str(model), options, providers=["CPUExecutionProvider"])
        _SESSIONS[model] = session
    return session


def remove_background(image: Image.Image, model: str | Path, *,
                      token: CancelToken | None = None) -> Image.Image:
    """Return the input subject with a soft alpha mask and original transparency retained."""
    try:
        import numpy as np
        source = image.convert("RGBA")
        rgb = Image.new("RGB", source.size, "white")
        rgb.paste(source, mask=source.getchannel("A"))
        session = _session(Path(model))
        if token:
            token.check()
        sample = np.asarray(rgb.resize((1024, 1024), Image.Resampling.LANCZOS), dtype=np.float32)
        sample = sample / max(float(sample.max()), 1e-6) - 0.5
        sample = sample.transpose(2, 0, 1)[None]
        prediction = session.run(None, {session.get_inputs()[0].name: sample})[0][0, 0]
        if token:
            token.check()
        low, high = float(prediction.min()), float(prediction.max())
        prediction = (prediction - low) / max(high - low, 1e-6)
        mask = Image.fromarray((prediction * 255).astype("uint8")).resize(rgb.size, Image.Resampling.LANCZOS)
        mask = ImageChops.multiply(mask, source.getchannel("A"))
        if not mask.point(lambda value: 255 if value > 8 else 0).getbbox():
            raise ConversionError("No subject found in this image")
        source.putalpha(mask)
        return source
    except ConversionError:
        raise
    except Exception as exc:
        raise ConversionError(f"Background removal failed: {exc}") from exc
