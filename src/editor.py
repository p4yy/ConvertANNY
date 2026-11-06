"""ConvertANNY crop and resize dialog with an asynchronous subject preview."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QSignalBlocker, QTimer
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import (QButtonGroup,QCheckBox,QComboBox,QDialog,QFrame,QGridLayout,
    QHBoxLayout,QLabel,QPushButton,QSizePolicy,QSpinBox,QToolButton,QVBoxLayout)

import engine
import i18n
from i18n import tr
from crop_canvas import CropCanvas,pil_to_qimage

ASPECTS = [("Free",None),("Original","orig"),("1:1",1),("4:3",4/3),("3:2",1.5),
           ("16:9",16/9),("9:16",9/16),("4:5",.8)]
_PREVIEWS = ThreadPoolExecutor(max_workers=1,thread_name_prefix="ConvertANNY-preview")
EDITOR_CSS = """
QFrame#side { background:$side; border-radius:12px; }
QLabel#section { color:$dim; font-weight:600; padding-top:4px; }
QLabel#dim { color:$faint; font-size:11px; }
QToolButton { color:$text; background:$surface; border:1px solid $border; border-radius:6px; padding:6px 4px; }
QToolButton:hover { background:$hover; }
QToolButton:checked { background:$accent; border-color:$accent; color:$on_accent; }
QSpinBox { color:$text; background:$surface; border:1px solid $border; border-radius:8px; min-height:38px; padding:0 10px; }
QSpinBox QLineEdit { border:none; background:transparent; padding:0; }
QSpinBox::up-button,QSpinBox::down-button { width:0; border:none; }
"""


class CropResizeDialog(QDialog):
    def __init__(self,path: str,css: str,icon=None,ensure_model=None):
        super().__init__(None,Qt.Window|Qt.WindowStaysOnTopHint)
        self.path = path
        self.ensure_model = ensure_model
        self.rotate = 0
        self.flip_h = self.flip_v = False
        self._closed = False
        self._future = None
        self.nobg_preview = None
        self.setWindowTitle(f"ConvertANNY · {tr('Crop & Resize')} · {Path(path).name}")
        self.setStyleSheet(i18n.css(css+EDITOR_CSS))
        if icon is not None:self.setWindowIcon(icon)
        self.resize(1060,700)
        with engine.open_image(path) as source:
            self.src_size = source.size
            self.prev_pil = source.copy()
        self.prev_pil.thumbnail((1800,1800))
        self.base_preview = pil_to_qimage(self.prev_pil)
        layout = QHBoxLayout(self);layout.setContentsMargins(12,12,12,12);layout.setSpacing(12)
        self.canvas = CropCanvas();layout.addWidget(self.canvas,1)
        panel = QFrame();panel.setObjectName('side');panel.setFixedWidth(300);layout.addWidget(panel)
        controls = QVBoxLayout(panel);controls.setContentsMargins(14,14,14,14);controls.setSpacing(10)
        def section(label):
            heading = QLabel(tr(label));heading.setObjectName('section');controls.addWidget(heading)
        def button(text,callback):
            control = QToolButton();control.setText(text);control.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed)
            control.clicked.connect(lambda checked=False:callback());return control
        section('Aspect ratio')
        aspects = QGridLayout();self.aspect_group = QButtonGroup(self)
        for index,(label,value) in enumerate(ASPECTS):
            control = button(tr(label),lambda value=value:self._set_aspect(value))
            control.setCheckable(True);self.aspect_group.addButton(control,index);aspects.addWidget(control,index//4,index%4)
        self.aspect_group.button(0).setChecked(True);controls.addLayout(aspects)
        section('Rotate & flip');orientation = QHBoxLayout()
        for symbol,label,callback in [('⟲','Rotate left',lambda:self._rotate(-90)),('⟳','Rotate right',lambda:self._rotate(90)),
                                       ('⇋','Flip horizontal',self._flip_h),('⇵','Flip vertical',self._flip_v)]:
            control = button(symbol,callback);control.setToolTip(tr(label));orientation.addWidget(control)
        controls.addLayout(orientation)
        self.nobg = QCheckBox(tr('Remove background'));controls.addWidget(self.nobg)
        self.nobg_lbl = QLabel();self.nobg_lbl.setObjectName('dim');self.nobg_lbl.setWordWrap(True);self.nobg_lbl.hide();controls.addWidget(self.nobg_lbl)
        section('Crop');self.crop_lbl = QLabel();self.crop_lbl.setObjectName('dim');controls.addWidget(self.crop_lbl)
        section('Output size');dimensions = QGridLayout();dimensions.setColumnStretch(1,1)
        self.w_spin,self.h_spin = QSpinBox(),QSpinBox()
        for row,(label,spin) in enumerate([('Width',self.w_spin),('Height',self.h_spin)]):
            spin.setRange(1,30000);spin.setSuffix(' px');spin.setAlignment(Qt.AlignCenter);spin.setMinimumWidth(150)
            dimensions.addWidget(QLabel(tr(label)),row,0);dimensions.addWidget(spin,row,1)
        controls.addLayout(dimensions)
        self.lock = QCheckBox(tr('Keep proportions'));self.lock.setChecked(True);controls.addWidget(self.lock)
        percentages = QHBoxLayout()
        for percent in (100,75,50,25):percentages.addWidget(button(f'{percent}%',lambda percent=percent:self._percent(percent)))
        controls.addLayout(percentages)
        section('Save as');self.fmt = QComboBox();extension = engine.ext_of(path)
        self.fmt.addItem(f"{tr('Same as original')} ({extension.upper()})",'')
        for extension_option in ('png','jpg','webp','avif','tiff','bmp'):
            if extension_option!=extension:self.fmt.addItem(extension_option.upper(),extension_option)
        controls.addWidget(self.fmt);controls.addStretch()
        reset = QPushButton(tr('Reset'));reset.clicked.connect(self._reset);controls.addWidget(reset)
        footer = QHBoxLayout();cancel = QPushButton(tr('Cancel'));cancel.clicked.connect(self.reject)
        self.save = QPushButton(tr('Save copy'));self.save.setDefault(True);self.save.clicked.connect(self.accept)
        footer.addWidget(cancel);footer.addWidget(self.save,1);controls.addLayout(footer)
        help_text = QLabel(tr('Drag the box or its corners. Double-click the image to reset the crop.'))
        help_text.setObjectName('dim');help_text.setWordWrap(True);controls.addWidget(help_text)
        self.canvas.changed.connect(self._crop_changed)
        self.w_spin.valueChanged.connect(lambda:self._size_edited('w'))
        self.h_spin.valueChanged.connect(lambda:self._size_edited('h'))
        self.nobg.toggled.connect(self._toggle_nobg)
        self._poll = QTimer(self);self._poll.setInterval(80);self._poll.timeout.connect(self._preview_finished)
        self.finished.connect(self._finish)
        self._rebuild_preview()

    def _finish(self,*args):
        self._closed = True
        self._poll.stop()
        if self._future is not None:self._future.cancel()

    def _rebuild_preview(self,keep_crop=False):
        image = self.nobg_preview if self.nobg.isChecked() and self.nobg_preview is not None else self.base_preview
        image = image.transformed(QTransform().rotate(self.rotate),Qt.SmoothTransformation).mirrored(self.flip_h,self.flip_v)
        width,height = self.src_size
        dimensions = QSize(height,width) if self.rotate%180 else QSize(width,height)
        if not keep_crop:
            aspect = ASPECTS[max(0,self.aspect_group.checkedId())][1]
            self.canvas.aspect = dimensions.width()/dimensions.height() if aspect=='orig' else aspect
        self.canvas.set_image(image,dimensions,keep_crop)

    def _set_aspect(self,value):
        if value=='orig':value = self.canvas.full.width()/self.canvas.full.height()
        self.canvas.set_aspect(value)

    def _rotate(self,degrees):
        self.rotate = (self.rotate+degrees)%360;self._rebuild_preview()

    def _toggle_flip(self,axis):
        """Flip the preview along 'h' or 'v' and redraw it."""
        attribute = 'flip_'+axis
        setattr(self,attribute,not getattr(self,attribute))
        self._rebuild_preview()

    def _flip_h(self):
        self._toggle_flip('h')

    def _flip_v(self):
        self._toggle_flip('v')

    def _reset(self):
        self.rotate = 0;self.flip_h = self.flip_v = False
        self.nobg.setChecked(False);self.aspect_group.button(0).setChecked(True);self._rebuild_preview()

    def _output_size(self,width,height):
        with QSignalBlocker(self.w_spin),QSignalBlocker(self.h_spin):
            self.w_spin.setValue(max(1,round(width)));self.h_spin.setValue(max(1,round(height)))

    def _crop_changed(self):
        rectangle = self.canvas.crop
        self.crop_lbl.setText(f'{round(rectangle.width())} × {round(rectangle.height())} px   ·   x {round(rectangle.x())}, y {round(rectangle.y())}')
        self._output_size(rectangle.width(),rectangle.height())

    def _size_edited(self,dimension):
        if not self.lock.isChecked():return
        ratio = self.canvas.crop.width()/max(1,self.canvas.crop.height())
        width,height = self.w_spin.value(),self.h_spin.value()
        self._output_size(width,width/ratio) if dimension=='w' else self._output_size(height*ratio,height)

    def _percent(self,percent):
        self._output_size(self.canvas.crop.width()*percent/100,self.canvas.crop.height()*percent/100)

    def _toggle_nobg(self,enabled):
        if not enabled:
            self.nobg_lbl.hide();self._rebuild_preview(True);return
        if self.nobg_preview is not None:
            self._rebuild_preview(True);return
        if not engine.model_ready('isnet'):
            with QSignalBlocker(self.nobg):self.nobg.setChecked(False)
            if self.ensure_model is not None:
                def downloaded():
                    if not self._closed:self.nobg.setChecked(True)
                self.ensure_model('isnet',tr('Remove background'),downloaded)
            return
        self.nobg_lbl.setText(tr('Finding the subject…'));self.nobg_lbl.show()
        self.nobg.setEnabled(False);self.save.setEnabled(False)
        self._future = _PREVIEWS.submit(engine.remove_bg_image,self.prev_pil.copy());self._poll.start()

    def _preview_finished(self):
        if self._future is None or not self._future.done():return
        self._poll.stop();self.nobg.setEnabled(True);self.save.setEnabled(True)
        try:
            result = self._future.result();self.nobg_preview = pil_to_qimage(result)
            self.nobg_lbl.hide();self._rebuild_preview(True)
        except Exception as error:
            with QSignalBlocker(self.nobg):self.nobg.setChecked(False)
            self.nobg_lbl.setText(str(error));self.nobg_lbl.show();self._rebuild_preview(True)
        finally:self._future = None

    def params(self):
        rectangle = self.canvas.crop
        return dict(rotate=self.rotate,flip_h=self.flip_h,flip_v=self.flip_v,remove_bg=self.nobg.isChecked(),
                    box=rectangle.getCoords(),size=(self.w_spin.value(),self.h_spin.value()),format=self.fmt.currentData())
