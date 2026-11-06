"""ConvertANNY dialog frame and close policy for share-aware windows."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QMessageBox,
                              QToolButton, QVBoxLayout, QWidget)

from i18n import tr


class FrontDialog(QDialog):
    """Centered title layout with an explicit, safe lifecycle for active shares."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.back: Callable[[], None] | None = None
        self.keep_hides = False
        self._leaving = False
        self._fronted = False
        self._back_button: QToolButton | None = None
        self._back_pad: QWidget | None = None

    def header(self, layout: QVBoxLayout, title: str, subtitle: str = "") -> QLabel:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        button = QToolButton(self)
        button.setObjectName("back")
        button.setText(tr("Back"))
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        button.setIconSize(QSize(14, 14))
        button.setCursor(Qt.PointingHandCursor)
        button.setToolTip(tr("Choose another way to send"))
        button.setVisible(self.back is not None)
        button.clicked.connect(self._return_to_chooser)
        spacer = QWidget(self)
        spacer.setFixedWidth(max(74, button.sizeHint().width()))
        spacer.setVisible(self.back is not None)
        heading = QLabel(title, self)
        heading.setObjectName("title")
        heading.setAlignment(Qt.AlignCenter)
        row.addWidget(button)
        row.addWidget(heading, 1)
        row.addWidget(spacer)
        layout.addLayout(row)
        self._back_button, self._back_pad = button, spacer
        self._set_back_controls()
        if subtitle:
            caption = QLabel(subtitle, self)
            caption.setObjectName("sub")
            caption.setAlignment(Qt.AlignCenter)
            caption.setWordWrap(True)
            caption.setMaximumWidth(372)
            layout.addWidget(caption, 0, Qt.AlignHCenter)
        layout.addSpacing(4)
        return heading

    @staticmethod
    def buttons(layout: QVBoxLayout, *buttons):
        row = QHBoxLayout()
        row.setSpacing(8)
        for button in buttons:
            button.setMinimumHeight(34)
            row.addWidget(button, 1)
        layout.addSpacing(4)
        layout.addLayout(row)

    def sharing(self) -> bool:
        return False

    def stop_sharing(self):
        return None

    def stop_question(self) -> str:
        return ""

    def _ask_stop(self):
        box = QMessageBox(self)
        box.setWindowTitle("ConvertANNY — " + tr("Send to phone"))
        if self.styleSheet():
            box.setStyleSheet(self.styleSheet())
        box.setText("<b>" + tr("Stop sharing?") + "</b>")
        box.setInformativeText(self.stop_question())
        stop = box.addButton(tr("Stop sharing"), QMessageBox.DestructiveRole)
        keep = box.addButton(tr("Keep sharing"), QMessageBox.AcceptRole)
        box.addButton(tr("Cancel"), QMessageBox.RejectRole)
        box.setDefaultButton(keep)
        box.exec()
        clicked = box.clickedButton()
        if clicked is stop:
            return "stop"
        if clicked is keep:
            return "keep"
        return None

    def leave_ok(self, event=None) -> bool:
        if self._leaving or not self.sharing():
            return True
        choice = self._ask_stop()
        if choice is None:
            if event is not None:
                event.ignore()
            return False
        if choice == "keep" and self.keep_hides:
            if event is not None:
                event.ignore()
            self.hide()
            return False
        if choice == "stop":
            self.stop_sharing()
        self._leaving = True
        return True

    def _return_to_chooser(self):
        if not self._leaving and self.sharing():
            choice = self._ask_stop()
            if choice is None:
                return
            if choice == "keep" and self.keep_hides:
                self.hide()
            else:
                if choice == "stop":
                    self.stop_sharing()
                self._leaving = True
                self.close()
        else:
            self._leaving = True
            self.close()
        if self.back is not None:
            QTimer.singleShot(0, self.back)

    def showEvent(self, event):
        if self._back_button is not None:
            self._set_back_controls()
        super().showEvent(event)
        if not self._fronted:
            self._fronted = True
            QTimer.singleShot(0, self._raise_once)

    def _set_back_controls(self):
        from ui_icons import navigation_icon
        visible = self.back is not None
        rtl = self.layoutDirection() == Qt.RightToLeft
        import theme
        self._back_button.setIcon(navigation_icon(
            "chevron_right" if rtl else "chevron_left",
            normal=theme.hexc("dim"), selected=theme.hexc("text"),
            accent=theme.hexc("accent"), background=theme.hexc("bg")))
        self._back_button.setVisible(visible)
        self._back_pad.setVisible(visible)

    def _raise_once(self):
        self.raise_()
        self.activateWindow()
        try:
            import winsys
            winsys.bring_to_front(int(self.winId()))
        except Exception:
            pass
