"""Exercise the owned dialog layout and share-aware exit policy offscreen."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget
from dialog_base import FrontDialog


class SharedDialog(FrontDialog):
    def __init__(self):
        super().__init__()
        self.active = True
        self.stopped = False

    def sharing(self):
        return self.active

    def stop_sharing(self):
        self.stopped = True
        self.active = False

    def stop_question(self):
        return "A test share is active."


def check():
    app = QApplication.instance() or QApplication([])
    dialog = SharedDialog()
    body = QWidget()
    layout = QVBoxLayout(body)
    title = dialog.header(layout, "Send files", "Two selected files")
    action = QPushButton("Continue")
    dialog.buttons(layout, action)
    assert isinstance(title, QLabel) and title.objectName() == "title"
    assert dialog._back_button is not None and not dialog._back_button.isVisible()

    class Event:
        ignored = False
        def ignore(self): self.ignored = True

    event = Event()
    dialog._ask_stop = lambda: None
    assert not dialog.leave_ok(event) and event.ignored and not dialog.stopped
    dialog._ask_stop = lambda: "stop"
    assert dialog.leave_ok() and dialog.stopped and dialog._leaving

    hidden = SharedDialog()
    hidden.keep_hides = True
    hidden._ask_stop = lambda: "keep"
    hidden.show();app.processEvents()
    assert not hidden.leave_ok() and not hidden.isVisible() and not hidden._leaving
    hidden.close()
    body.deleteLater();dialog.deleteLater();hidden.deleteLater();app.processEvents()
    print("Owned dialog header, action row, cancel/stop/keep close policies passed")


if __name__ == "__main__":
    check()
