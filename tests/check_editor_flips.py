"""Crop/resize dialog: flip toggles flip exactly one axis, redraw the preview, and reset clears them."""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from PIL import Image
from PySide6.QtWidgets import QApplication
import editor


def check():
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "sample.png"
        Image.new("RGB", (40, 20), (200, 30, 30)).save(path)
        dialog = editor.CropResizeDialog(str(path), "")
        redraws = []
        real = dialog._rebuild_preview
        dialog._rebuild_preview = lambda: (redraws.append(1), real())[1]
        try:
            assert (dialog.flip_h, dialog.flip_v) == (False, False)
            dialog._flip_h()
            assert (dialog.flip_h, dialog.flip_v) == (True, False) and len(redraws) == 1
            dialog._flip_v()
            assert (dialog.flip_h, dialog.flip_v) == (True, True) and len(redraws) == 2
            dialog._flip_h()
            assert (dialog.flip_h, dialog.flip_v) == (False, True) and len(redraws) == 3
            assert dialog.result_params()["flip_v"] is True if hasattr(dialog, "result_params") else True
            dialog._reset()
            assert (dialog.flip_h, dialog.flip_v, dialog.rotate) == (False, False, 0)
        finally:
            dialog.close()
    print("Crop/resize flip toggles, redraws and reset passed")


if __name__ == "__main__":
    check()
