"""ConvertANNY job notifications with independent cancellation and output actions."""
from pathlib import Path
from PySide6.QtCore import Qt,QObject,QTimer,QRectF,QPointF,Signal,QPropertyAnimation,QVariantAnimation,QEasingCurve
from PySide6.QtGui import QPainter,QPen,QColor,QPixmap,QCursor,QGuiApplication,QTextDocumentFragment
from PySide6.QtWidgets import QWidget,QHBoxLayout,QVBoxLayout,QLabel,QPushButton
import theme,i18n
from i18n import tr


class Toast(QWidget):
    closed=Signal(object)
    resized=Signal()
    def __init__(self,*,reveal=lambda paths:None,play_sound=lambda kind:None,settings=None):
        super().__init__(None,Qt.Tool|Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground);self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedWidth(360);self._reveal_paths=reveal;self._play_sound=play_sound;self._settings=settings
        self.wanted=False;self.target=None;self.on_cancel=None;self.on_undo=None;self._auto_ms=0;self._fading=False
        self._kind='info';self._phase=0;self._tick=1.;self._sound_for_this=False
        layout=QHBoxLayout(self);layout.setContentsMargins(16,12,12,12);layout.setSpacing(10)
        self.icon=QLabel();self.icon.setFixedSize(30,30);layout.addWidget(self.icon)
        copy=QVBoxLayout();copy.setSpacing(1);self.title=QLabel();self.body=QLabel();self.body.setWordWrap(True)
        self.title.setObjectName('title');self.body.setObjectName('body');self.title.setTextFormat(Qt.PlainText)
        copy.addWidget(self.title);copy.addWidget(self.body);layout.addLayout(copy,1)
        self.btn=QPushButton();self.undo_btn=QPushButton();self.cancel_btn=QPushButton()
        for button in (self.btn,self.undo_btn,self.cancel_btn):
            button.setCursor(Qt.PointingHandCursor);layout.addWidget(button)
        self.btn.setObjectName('show');self.undo_btn.setObjectName('secondary');self.cancel_btn.setObjectName('secondary')
        self.btn.clicked.connect(self._reveal);self.undo_btn.clicked.connect(self._undo);self.cancel_btn.clicked.connect(self._cancel)
        self.close_btn=QPushButton('×');self.close_btn.setObjectName('dismiss');self.close_btn.setFixedSize(24,24);self.close_btn.setAccessibleName(tr('Dismiss notification'))
        self.close_btn.setToolTip(tr('Dismiss'));self.close_btn.setCursor(Qt.PointingHandCursor);self.close_btn.clicked.connect(self.close_card);layout.addWidget(self.close_btn)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self._fade_out)
        self.spin_timer=QTimer(self);self.spin_timer.setInterval(60);self.spin_timer.timeout.connect(self._spin)
        self._fade=QPropertyAnimation(self,b'windowOpacity',self);self._fade.setDuration(200);self._fade.finished.connect(self._fade_finished)
        self._success=QVariantAnimation(self);self._success.setDuration(520);self._success.setEasingCurve(QEasingCurve.OutCubic)
        self._success.valueChanged.connect(self._tick_frame);self.restyle()

    def restyle(self):
        self.setStyleSheet(i18n.css("""
            QLabel#title { color:$text; font-weight:600; }
            QLabel#body { color:$dim; font-size:13px; font-weight:400; }
            QPushButton { border:0; border-radius:11px; padding:4px 12px; }
            QPushButton#show { background:$accent; color:$on_accent; }
            QPushButton#show:hover { background:$accent2; }
            QPushButton#secondary { background:$button; color:$text; }
            QPushButton#secondary:hover { background:$hover; }
            QPushButton#dismiss { background:transparent; color:$dim; padding:0; border-radius:12px; font-size:18px; }
            QPushButton#dismiss:hover { background:$hover; color:$text; }
        """))
        self.btn.setText(tr('Show'));self.undo_btn.setText(tr('Undo'));self.cancel_btn.setText(tr('Cancel'))
        self._paint_icon()
    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(theme.color('line'),1));painter.setBrush(theme.color('panel'))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1,1,-1,-1),14,14)
    def _place(self):self.adjustSize();self.resized.emit()
    def _spin(self):self._phase=(self._phase+24)%360;self._paint_icon()
    def _tick_frame(self,value):self._tick=float(value);self._paint_icon()
    def _paint_icon(self):
        ratio=self.devicePixelRatioF();pixmap=QPixmap(round(30*ratio),round(30*ratio));pixmap.setDevicePixelRatio(ratio);pixmap.fill(Qt.transparent)
        painter=QPainter(pixmap);painter.setRenderHint(QPainter.Antialiasing)
        if self._kind=='busy':
            painter.setPen(QPen(theme.color('busy_track'),3));painter.drawEllipse(QRectF(4,4,22,22))
            painter.setPen(QPen(theme.color('accent'),3,Qt.SolidLine,Qt.RoundCap));painter.drawArc(QRectF(4,4,22,22),-self._phase*16,1600)
        else:
            role={'ok':'ok','err':'danger'}.get(self._kind,'accent')
            painter.setPen(Qt.NoPen);painter.setBrush(theme.color(role));radius=12*(.5+.5*self._tick) if self._kind=='ok' else 12
            painter.drawEllipse(QPointF(15,15),radius,radius)
            painter.setPen(QPen(QColor('white'),2.6,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin))
            if self._kind=='ok':
                progress=max(0,min(1,(self._tick-.25)/.75));a,b,c=QPointF(9,15),QPointF(13,19),QPointF(21,11)
                if progress<.35:painter.drawLine(a,a+(b-a)*(progress/.35))
                else:painter.drawLine(a,b);painter.drawLine(b,b+(c-b)*((progress-.35)/.65))
            elif self._kind=='err':painter.drawLine(10,10,20,20);painter.drawLine(20,10,10,20)
            else:painter.drawLine(15,9,15,17);painter.drawPoint(15,21)
        painter.end();self.icon.setPixmap(pixmap)
    def _show(self,title,body,kind,show_btn=False,cancel=None,ms=None):
        self.timer.stop();self._fading=False;self._fade.stop();self._success.stop();self.setWindowOpacity(1)
        self._kind=kind;self._tick=1.;self._auto_ms=4000 if ms else 0
        self.title.setText(str(title));self.body.setText(str(body));self.btn.setVisible(show_btn)
        self.on_cancel=cancel;self.on_undo=None;self.undo_btn.hide();self.cancel_btn.setVisible(cancel is not None);self.cancel_btn.setEnabled(True)
        self.spin_timer.start() if kind=='busy' else self.spin_timer.stop()
        animate=self._settings is None or self._settings().value('finish_anim','true')=='true'
        if kind=='ok' and animate:
            self._tick=0.;self._success.setStartValue(0.);self._success.setEndValue(1.);self._success.start()
        if kind=='err' or (kind=='ok' and self._sound_for_this):self._play_sound(kind)
        self._sound_for_this=False;self.restyle()
        self.setAccessibleName(str(title)+'. '+QTextDocumentFragment.fromHtml(str(body)).toPlainText())
        self.wanted=True;self._place();self.show()
        if self._auto_ms:self.timer.start(self._auto_ms-self._fade.duration())
    def show_busy(self,title,body,on_cancel=None):self._show(title,body,'busy',cancel=on_cancel)
    def show_msg(self,title,body,kind='info',ms=2600):self._show(title,body,kind,ms=ms);return self
    def show_result(self,title,outs):
        paths=[str(path) for path in outs if path];self.target=paths or None
        body=Path(paths[0]).name if len(paths)==1 else tr('{n} items saved',n=len(paths))
        self._show(title,body,'ok',show_btn=bool(paths),ms=5000);return self
    def set_undo(self,callback):
        self.on_undo=callback;self.undo_btn.setVisible(callback is not None)
        if callback and self.timer.isActive():self.timer.start(3800)
        self._place()
    def _cancel(self):
        callback=self.on_cancel;self.on_cancel=None;self.cancel_btn.setEnabled(False)
        if callback:
            try:callback()
            except Exception as error:self.show_msg(tr("Couldn't cancel"),str(error),'err',5000)
    def _undo(self):
        callback=self.on_undo;self.on_undo=None
        if callback:
            try:success=callback()
            except Exception as error:
                self.show_msg(tr("Couldn't undo"),str(error),'err',5000);return
            self.btn.hide();self.undo_btn.hide();self.target=None
            self.title.setText(tr('Undone') if success else tr("Couldn't undo"))
            if success:self.body.setText(tr('The new file went to the Recycle Bin.'))
            self._kind='info' if success else 'err';self._paint_icon();self._place();self.timer.start(3000)
    def _reveal(self):
        if self.target:self._reveal_paths(self.target)
        self.close_card()
    def _fade_out(self):
        if self.underMouse():return
        self._fading=True;self._fade.setStartValue(self.windowOpacity());self._fade.setEndValue(0.);self._fade.start()
    def _fade_finished(self):
        if self._fading:self.close_card()
    def enterEvent(self,event):
        self._fading=False;self._fade.stop();self.setWindowOpacity(1);self.timer.stop();super().enterEvent(event)
    def leaveEvent(self,event):
        if self.wanted and self._auto_ms:self.timer.start(3800)
        super().leaveEvent(event)
    def close_card(self):
        if not self.wanted:return
        self.wanted=False;self._fading=False;self.timer.stop();self.spin_timer.stop();self._fade.stop();self._success.stop();self.hide();self.closed.emit(self)


class ToastManager(QObject):
    def __init__(self,*,reveal=lambda paths:None,play_sound=lambda kind:None,settings=None):
        super().__init__();self.cards=[];self._options=dict(reveal=reveal,play_sound=play_sound,settings=settings)
    def _new(self):
        card=Toast(**self._options);card.closed.connect(self._closed);card.resized.connect(self.reflow);self.cards.append(card)
        while len(self.cards)>6:
            completed=next((item for item in self.cards[:-1] if item._kind!='busy'),None)
            if completed is None:break
            completed.close_card()
        return card
    def _closed(self,card):
        if card in self.cards:self.cards.remove(card)
        card.deleteLater();self.reflow()
    def reflow(self):
        screen=QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen is None:return
        area=screen.availableGeometry();bottom=area.bottom()-18
        for card in reversed(self.cards):
            if not card.wanted:continue
            card.adjustSize();bottom-=card.height()
            x=area.left()+18 if i18n.is_rtl() else area.right()-card.width()-18
            card.move(x,bottom);bottom-=10
    def restyle(self):
        for card in self.cards:card.restyle()
    def show_busy(self,title,body,on_cancel=None):
        card=self._new();card.show_busy(title,body,on_cancel);return card
    def show_msg(self,title,body,kind='info',ms=2600):
        card=self._new();return card.show_msg(title,body,kind,ms)
    def show_result(self,title,outs):
        card=self._new();return card.show_result(title,outs)
    def set_undo(self,callback):
        if self.cards:self.cards[-1].set_undo(callback)
