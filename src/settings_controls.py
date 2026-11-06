"""ConvertANNY settings controls and shortcut capture."""
from PySide6.QtCore import Qt,QRectF,QVariantAnimation,QEasingCurve,QEvent,Signal
from PySide6.QtGui import QPainter,QPen,QColor,QKeySequence
from PySide6.QtWidgets import QPushButton,QWidget,QLabel,QHBoxLayout,QVBoxLayout,QApplication
import theme
from i18n import tr


def qt_key_name(key):
    aliases={Qt.Key_Control:'Ctrl',Qt.Key_Meta:'Win',Qt.Key_Return:'Enter',Qt.Key_Enter:'Enter',
             Qt.Key_CapsLock:'CapsLock',Qt.Key_PageUp:'PageUp',Qt.Key_PageDown:'PageDown'}
    if key in aliases:return aliases[key]
    if key in (Qt.Key_Escape,Qt.Key_unknown):return None
    text=QKeySequence(int(key)).toString(QKeySequence.PortableText)
    if text in ('Shift','Alt','Tab','Space','Insert','Delete','Home','End','Left','Right','Up','Down','Backspace'):
        return text
    if len(text)==1 and text!='+':return text.upper() if text.isalpha() else text
    if text.startswith('F') and text[1:].isdigit() and 1<=int(text[1:])<=24:return text
    return None


def combo_text(names):
    order={name:index for index,name in enumerate(('Ctrl','Shift','Alt','Win'))}
    mouse={name:20+index for index,name in enumerate(('LeftClick','RightClick','MiddleMouse','Mouse4','Mouse5'))}
    return '+'.join(sorted(dict.fromkeys(names),key=lambda name:order.get(name,mouse.get(name,10))))


class ToggleSwitch(QPushButton):
    def __init__(self,on=False,parent=None):
        super().__init__(parent)
        self.setCheckable(True);self.setChecked(bool(on));self.setAutoDefault(False)
        self.setFixedSize(46,26);self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet('QPushButton { background:transparent; border:0; padding:0; }')
        self._position=float(bool(on))
        self._motion=QVariantAnimation(self);self._motion.setDuration(140)
        self._motion.setEasingCurve(QEasingCurve.OutCubic)
        self._motion.valueChanged.connect(self._frame);self.toggled.connect(self._animate)

    def _frame(self,value):
        self._position=float(value);self.update()

    def _animate(self,checked):
        self._motion.stop()
        target=float(checked)
        if not self.isVisible():self._frame(target);return
        self._motion.setStartValue(self._position);self._motion.setEndValue(target);self._motion.start()

    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():painter.setOpacity(.45)
        track=QRectF(1,2,44,22)
        painter.setPen(QPen(theme.color('accent') if self.isChecked() else theme.color('line'),1))
        painter.setBrush(theme.color('accent') if self.isChecked() else theme.color('button'))
        painter.drawRoundedRect(track,11,11)
        painter.setPen(Qt.NoPen);painter.setBrush(QColor('white') if self.isChecked() else theme.color('text'))
        painter.drawEllipse(QRectF(4+22*self._position,5,16,16))
        if self.hasFocus():
            painter.setPen(QPen(theme.color('text'),1,Qt.DotLine));painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(QRectF(.5,.5,45,25),12,12)


class SwitchBox(QWidget):
    toggled=Signal(bool)
    def __init__(self,text='',parent=None):
        super().__init__(parent)
        self.sw=ToggleSwitch(parent=self);self.label=QLabel(text,self);self.label.setWordWrap(True)
        self.sw.setAccessibleName(text)
        layout=QHBoxLayout(self);layout.setContentsMargins(0,2,0,2);layout.setSpacing(12)
        layout.addWidget(self.sw);layout.addWidget(self.label,1)
        self.sw.toggled.connect(self.toggled)

    def isChecked(self):return self.sw.isChecked()
    def setChecked(self,value):self.sw.setChecked(bool(value))
    def setText(self,text):self.label.setText(text);self.sw.setAccessibleName(text)
    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton and self.isEnabled():self.sw.toggle();event.accept()
        else:super().mousePressEvent(event)


def setting_row(switch,title,desc,extra=None):
    layout=QHBoxLayout();layout.setSpacing(12);layout.addWidget(switch,0,Qt.AlignTop)
    copy=QVBoxLayout();copy.setSpacing(1)
    heading=QLabel(title);heading.setStyleSheet('font-weight:700; font-size:10.5pt')
    description=QLabel(desc);description.setWordWrap(True);description.setObjectName('dim')
    copy.addWidget(heading);copy.addWidget(description);layout.addLayout(copy,1)
    if extra is not None:
        caption=QLabel(tr('Opens'));caption.setObjectName('dim');layout.addWidget(caption)
        extra.setMinimumWidth(150);layout.addWidget(extra);extra.setEnabled(switch.isChecked())
        switch.toggled.connect(extra.setEnabled)
    return layout


class KeyCapture(QPushButton):
    changed=Signal(str)
    def __init__(self,spec='None',parent=None):
        super().__init__(parent)
        self.spec=spec or 'None';self._capturing=False;self._held=set();self._sequence=[]
        self.setObjectName('keycap');self.setMinimumWidth(220);self.setAutoDefault(False)
        self.setCursor(Qt.PointingHandCursor);self.clicked.connect(self._listen);self._render()

    def _render(self):
        text=tr('Press a key or a combination…') if self._capturing and not self._sequence else self.spec
        if self._capturing and self._sequence:text=combo_text(self._sequence)+' …'
        self.setText(' + '.join(tr(part) for part in text.split('+')))

    def _listen(self):
        self._capturing=True;self._held.clear();self._sequence=[]
        self.setFocus();QApplication.instance().installEventFilter(self);self._render()

    def _finish(self,spec=None):
        QApplication.instance().removeEventFilter(self);self._capturing=False
        if spec is not None and spec!=self.spec:self.spec=spec;self.changed.emit(spec)
        self._render()

    def set_spec(self,spec):
        self.spec=spec or 'None';self._render()

    def eventFilter(self,watched,event):
        if not self._capturing:return False
        kind=event.type()
        if kind in (QEvent.KeyPress,QEvent.KeyRelease):
            if event.key()==Qt.Key_Escape:self._finish();return True
            if event.isAutoRepeat():return True
            name=qt_key_name(event.key())
            if name:
                if kind==QEvent.KeyPress:
                    self._held.add(name)
                    if name not in self._sequence:self._sequence.append(name)
                    self._render()
                else:
                    self._held.discard(name)
                    if not self._held and self._sequence:self._finish(combo_text(self._sequence))
            return True
        if kind==QEvent.MouseButtonPress:
            mouse={Qt.LeftButton:'LeftClick',Qt.RightButton:'RightClick',Qt.MiddleButton:'MiddleMouse',Qt.BackButton:'Mouse4',Qt.ForwardButton:'Mouse5'}
            name=mouse.get(event.button())
            if name and (self._held or event.button() in (Qt.MiddleButton,Qt.BackButton,Qt.ForwardButton)):
                self._finish(combo_text([*self._sequence,name]))
            elif event.button()==Qt.LeftButton:self._finish()
            return True
        return super().eventFilter(watched,event)

    def focusOutEvent(self,event):
        if self._capturing:self._finish()
        super().focusOutEvent(event)

    def hideEvent(self,event):
        if self._capturing:self._finish()
        super().hideEvent(event)
