"""ConvertANNY watermark controls with previews rendered by the export engine."""
from __future__ import annotations
import json
import tempfile
from pathlib import Path
from PySide6.QtCore import Qt,QTimer,QSettings
from PySide6.QtGui import QColor,QImage,QPixmap
from PySide6.QtWidgets import QWidget,QHBoxLayout,QVBoxLayout,QLabel,QLineEdit,QPushButton,QSlider,QColorDialog
import pymupdf
import engine
from convertanny_core.documents import watermark_pdf
from convertanny_core.paths import OutputPolicy
from i18n import tr


class WatermarkEditor(QWidget):
    def __init__(self,paths):
        super().__init__()
        pdf=next((path for path in paths if engine.EXT_CATEGORY.get(engine.ext_of(path))=='pdf'),None)
        if pdf is None:raise ValueError('Choose a PDF to watermark')
        self.logo=next((path for path in paths if engine.EXT_CATEGORY.get(engine.ext_of(path))=='image'),None)
        self._closed=False
        self._work=tempfile.TemporaryDirectory(prefix='convertanny-watermark-')
        self._source=Path(self._work.name)/'preview.pdf'
        with pymupdf.open(pdf) as original,pymupdf.open() as first:
            if original.needs_pass or not original.page_count:
                self._work.cleanup();raise ValueError('Choose an unlocked PDF with at least one page')
            first.insert_pdf(original,from_page=0,to_page=0);first.save(self._source)
        self.settings=QSettings('ConvertANNY','ConvertANNY')
        try:saved=json.loads(str(self.settings.value('pdf_watermark','{}')))
        except (TypeError,ValueError):saved={}
        self.spec=dict(engine.WATERMARK_DEFAULT)
        if isinstance(saved,dict):self.spec.update({key:value for key,value in saved.items() if key in self.spec})
        layout=QHBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.view=QLabel();self.view.setMinimumSize(380,440);self.view.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.view,1);controls=QVBoxLayout();controls.setSpacing(8);layout.addLayout(controls)
        self._timer=QTimer(self);self._timer.setSingleShot(True);self._timer.setInterval(120);self._timer.timeout.connect(self._render)
        self.error=QLabel();self.error.setWordWrap(True);self.error.setObjectName('dim')
        if not self.logo:
            controls.addWidget(QLabel(tr('Text')));self.text=QLineEdit(str(self.spec['text']))
            self.text.textChanged.connect(lambda text:self._set('text',text));controls.addWidget(self.text)
            controls.addWidget(QLabel(tr('Color')));colors=QHBoxLayout()
            for color in ('#808080','#000000','#d0312d','#1f5fbf','#2e8b57','#ff8a00'):
                button=QPushButton();button.setFixedSize(28,28);button.setToolTip(color)
                button.setStyleSheet(f'background:{color};border:1px solid palette(mid);border-radius:14px;padding:0;')
                button.clicked.connect(lambda checked=False,color=color:self._set('color',color));colors.addWidget(button)
            custom=QPushButton('…');custom.setToolTip(tr('More colors…'));custom.clicked.connect(self._pick_color);colors.addWidget(custom);controls.addLayout(colors)
        controls.addWidget(QLabel(tr('Direction')));directions=QHBoxLayout()
        for symbol,angle in [('↗',45),('→',0),('↘',-45),('↑',90)]:
            button=QPushButton(symbol);button.setFixedWidth(46);button.clicked.connect(lambda checked=False,angle=angle:self.angle.setValue(angle));directions.addWidget(button)
        controls.addLayout(directions)
        self.angle=self._slider(controls,'angle',-90,90,1,'°')
        controls.addWidget(QLabel(tr('Size')));self.size=self._slider(controls,'size',10,100,100,'%')
        controls.addWidget(QLabel(tr('Strength')));self.opacity=self._slider(controls,'opacity',5,80,100,'%')
        controls.addWidget(self.error);controls.addStretch();self._render()

    def _slider(self,layout,key,minimum,maximum,scale,suffix):
        slider=QSlider(Qt.Horizontal);slider.setRange(minimum,maximum)
        try:value=round(float(self.spec[key])*scale)
        except (ValueError,TypeError):value=round(float(engine.WATERMARK_DEFAULT[key])*scale)
        slider.setValue(value);self.spec[key]=slider.value()/scale
        label=QLabel(f'{slider.value()}{suffix}');label.setFixedWidth(44)
        row=QHBoxLayout();row.addWidget(slider,1);row.addWidget(label);layout.addLayout(row)
        slider.valueChanged.connect(lambda value:(label.setText(f'{value}{suffix}'),self._set(key,value/scale)))
        return slider

    def _set(self,key,value):
        self.spec[key]=value
        if not self._closed:self._timer.start()

    def _pick_color(self):
        color=QColorDialog.getColor(QColor(self.spec['color']),self,tr('Color'))
        if color.isValid():self._set('color',color.name())

    def _render(self):
        if self._closed:return
        output=None
        try:
            output=watermark_pdf(self._source,str(self.spec['text']),logo=self.logo,
                angle=self.spec['angle'],size=self.spec['size'],opacity=self.spec['opacity'],color=self.spec['color'],
                policy=OutputPolicy(directory=Path(self._work.name),suffix=' marked'))
            with pymupdf.open(output) as document:
                page=document[0];scale=420/max(page.rect.width,page.rect.height)
                pixels=page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),alpha=False)
                image=QImage(pixels.samples,pixels.width,pixels.height,pixels.stride,QImage.Format_RGB888).copy()
            self.view.setPixmap(QPixmap.fromImage(image));self.error.clear()
        except Exception as error:self.error.setText(str(error))
        finally:
            if output is not None:Path(output).unlink(missing_ok=True)

    def value(self):
        return json.dumps(self.spec)

    def stop(self):
        if self._closed:return
        self._closed=True;self._timer.stop()
        self.settings.setValue('pdf_watermark',json.dumps(self.spec));self._work.cleanup()
