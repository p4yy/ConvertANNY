"""ConvertANNY getting-started window and looping drag demonstration."""
import math
from PySide6.QtCore import Qt,QTimer,QElapsedTimer,QRectF,QPointF
from PySide6.QtGui import QPainter,QPen,QPainterPath,QFont
from PySide6.QtWidgets import QDialog,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QCheckBox,QPushButton
import theme
from i18n import tr


class TourCanvas(QWidget):
    def __init__(self,key='Shift',parent=None):
        super().__init__(parent);self.key=key;self.setMinimumSize(620,260)
        self._clock=QElapsedTimer();self._clock.start();self._timer=QTimer(self);self._timer.setInterval(33);self._timer.timeout.connect(self.update)
    def step(self):return min(2,int((self._clock.elapsed()%6600)/2200))
    def showEvent(self,event):self._clock.restart();self._timer.start();super().showEvent(event)
    def hideEvent(self,event):self._timer.stop();super().hideEvent(event)
    def paintEvent(self,event):
        import runtime
        painter=QPainter(self);painter.setRenderHints(QPainter.Antialiasing|QPainter.SmoothPixmapTransform)
        painter.setPen(QPen(theme.color('border'),1));painter.setBrush(theme.color('surface'))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1,1,-1,-1),12,12)
        phase=(self._clock.elapsed()%6600)/1000
        center=QPointF(self.width()*.69,self.height()*.48)
        if phase>=2:
            painter.save();painter.setOpacity(min(1,(phase-2)/.35))
            for index in range(4):
                angle=-90+90*index;position=center+QPointF(math.cos(math.radians(angle))*74,math.sin(math.radians(angle))*74)
                target=phase>=3.4 and index==0
                painter.setBrush(theme.color('accent') if target else theme.color('button'));painter.setPen(QPen(theme.color('border'),1))
                painter.drawRoundedRect(QRectF(position.x()-35,position.y()-22,70,44),10,10)
                painter.setPen(theme.color('on_accent') if target else theme.color('text'))
                painter.drawText(QRectF(position.x()-35,position.y()-22,70,44),Qt.AlignCenter,['JPG','PNG','PDF','WebP'][index])
            painter.drawPixmap(round(center.x()-20),round(center.y()-20),runtime.app_icon().pixmap(40,40));painter.restore()
        if phase<4.4:
            progress=min(1,phase/2);ease=progress*progress*(3-2*progress)
            start=QPointF(self.width()*.22,self.height()*.45);finish=center+QPointF(-96,0)
            location=start+(finish-start)*ease
            if phase>3.4:
                travel=min(1,(phase-3.4));location=finish+(center+QPointF(0,-74)-finish)*travel
            painter.save();painter.setOpacity(1 if phase<4 else max(0,1-(phase-4)/.4))
            painter.setBrush(theme.color('surface'));painter.setPen(QPen(theme.color('border'),1))
            card=QRectF(location.x()-45,location.y()-38,90,76);painter.drawRoundedRect(card,10,10)
            painter.drawPixmap(round(location.x()-16),round(location.y()-29),runtime.app_icon().pixmap(32,32))
            painter.setPen(theme.color('text'));painter.drawText(QRectF(location.x()-45,location.y()+8,90,22),Qt.AlignCenter,'photo.heic')
            cursor=QPainterPath();cursor.moveTo(location+QPointF(30,22));cursor.lineTo(location+QPointF(34,44));cursor.lineTo(location+QPointF(40,37));cursor.lineTo(location+QPointF(48,35));cursor.closeSubpath()
            painter.setBrush(theme.color('text'));painter.setPen(QPen(theme.color('bg'),1));painter.drawPath(cursor);painter.restore()
        painter.setPen(theme.color('dim'));painter.drawText(QRectF(28,self.height()-44,220,24),Qt.AlignLeft|Qt.AlignVCenter,tr('Tap {key} while dragging',key=self.key))
        if phase>=4.4:
            rectangle=QRectF(self.width()*.49,self.height()-52,self.width()*.46,32)
            painter.setBrush(theme.color('button'));painter.setPen(QPen(theme.color('border'),1));painter.drawRoundedRect(rectangle,10,10)
            painter.setPen(theme.color('text'));painter.drawText(rectangle,Qt.AlignCenter,tr('Saved')+' · photo.jpg')


class TourDialog(QDialog):
    def __init__(self,app,parent=None):
        super().__init__(parent);import runtime
        self.setWindowTitle('ConvertANNY · '+tr('Getting started'));self.setWindowIcon(runtime.app_icon());self.resize(680,450)
        self._settings=runtime.settings();layout=QVBoxLayout(self);layout.setContentsMargins(24,22,24,22);layout.setSpacing(16)
        header=QHBoxLayout();logo=QLabel();logo.setPixmap(runtime.app_icon().pixmap(40,40));header.addWidget(logo)
        title=QLabel('ConvertANNY');title.setStyleSheet('font-size:20px;font-weight:600');header.addWidget(title);header.addStretch();layout.addLayout(header)
        subtitle=QLabel(tr('Convert files from the workspace or directly from File Explorer.'));subtitle.setWordWrap(True);layout.addWidget(subtitle)
        key=runtime.mode_keys().get('convert','Shift');key=runtime.key_label(key) if key!='None' else tr('Shake')
        self.canvas=TourCanvas(key);layout.addWidget(self.canvas)
        steps=QHBoxLayout()
        for text in [tr('1  Drag a file'),tr('2  Tap {key}',key=key),tr('3  Drop on a format')]:
            label=QLabel(text);label.setWordWrap(True);steps.addWidget(label,1)
        layout.addLayout(steps)
        hint=QLabel(tr('You can also right-click a file and choose ConvertANNY. Esc closes the orbit.'));hint.setWordWrap(True);hint.setObjectName('dim');layout.addWidget(hint)
        footer=QHBoxLayout();self.never=QCheckBox(tr("Don't show this again"));self.never.setChecked(self._settings.value('tour_at_start','true')!='true')
        self.never.toggled.connect(self._remember);footer.addWidget(self.never);footer.addStretch()
        help_button=QPushButton(tr('More help'));help_button.clicked.connect(lambda:(self.accept(),app.show_help()));footer.addWidget(help_button)
        done=QPushButton(tr('Got it'));done.setDefault(True);done.setObjectName('primary');done.clicked.connect(self.accept);footer.addWidget(done);layout.addLayout(footer)
    def _remember(self,checked):
        self._settings.setValue('tour_at_start','false' if checked else 'true');self._settings.sync()
