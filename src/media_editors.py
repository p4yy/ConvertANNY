"""ConvertANNY waveform trimming and video framing controls."""
from concurrent.futures import ThreadPoolExecutor
import tempfile
from pathlib import Path
from PySide6.QtCore import Qt,QTimer,QRectF,QPointF,QUrl,Signal
from PySide6.QtGui import QPainter,QPainterPath,QPen,QColor,QImage
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QPushButton,QLabel,QLineEdit
import engine,theme
from convertanny_core.media import waveform_peaks
from convertanny_core.model import CancelToken
from i18n import tr
_POOL=ThreadPoolExecutor(max_workers=2,thread_name_prefix='ConvertANNY-media-preview')


class WaveView(QWidget):
    changed=Signal();seek=Signal(float)
    def __init__(self,max_len):
        super().__init__();self.setMinimumSize(560,120);self.setMouseTracking(True)
        self.max_len=max_len;self.peaks=[];self.dur=0.;self.a=self.b=0.;self.v0=0.;self.v1=1.;self.head=None;self._drag=None
    def set_data(self,peaks,duration):
        self.peaks=list(peaks);self.dur=max(0,float(duration));self.v0=0.;self.v1=max(.001,self.dur)
        self.set_range(0,min(30,self.max_len,self.dur),'a')
    def _x(self,value):return (value-self.v0)/max(.001,self.v1-self.v0)*self.width()
    def _t(self,x):return max(0,min(self.dur,self.v0+x/max(1,self.width())*(self.v1-self.v0)))
    def set_range(self,start,end,keep='b'):
        minimum=min(.05,self.dur);length=min(self.dur,self.max_len,max(minimum,end-start))
        start=max(0,min(self.dur-length,start if keep=='a' else end-length))
        self.a,self.b=start,start+length;self.changed.emit();self.update()
    def _hit(self,x):
        if abs(x-self._x(self.a))<8:return 'a'
        if abs(x-self._x(self.b))<8:return 'b'
        return 'move' if self._x(self.a)<x<self._x(self.b) else 'new'
    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton and self.peaks:self._drag=(self._hit(event.position().x()),self._t(event.position().x()),self.a,self.b)
    def mouseMoveEvent(self,event):
        if self._drag is None:return
        mode,anchor,start,end=self._drag;position=self._t(event.position().x());minimum=min(.05,self.dur)
        if mode=='a':self.set_range(min(position,end-minimum),end,'a')
        elif mode=='b':self.set_range(start,max(position,start+minimum),'b')
        elif mode=='move':
            delta=max(-start,min(self.dur-end,position-anchor));self.set_range(start+delta,end+delta,'a')
        else:self.set_range(min(anchor,position),max(anchor,position),'a' if position>=anchor else 'b')
    def mouseReleaseEvent(self,event):
        if self._drag is not None:
            mode,anchor,start,end=self._drag
            if mode=='new' and abs(self._t(event.position().x())-anchor)<.01:self.set_range(anchor,anchor+end-start,'a');self.seek.emit(self.a)
        self._drag=None
    def wheelEvent(self,event):
        if not self.dur:return
        span=self.v1-self.v0;delta=event.angleDelta().y() or event.angleDelta().x()
        if event.modifiers()&Qt.ShiftModifier or event.angleDelta().x():
            self.v0=max(0,min(self.dur-span,self.v0-delta/120*span*.15))
        else:
            anchor=self._t(event.position().x());fraction=(anchor-self.v0)/max(.001,span)
            span=min(self.dur,max(min(2,self.dur),span*(.8 if delta>0 else 1.25)));self.v0=max(0,min(self.dur-span,anchor-fraction*span))
        self.v1=self.v0+span;self.update()
    def paintEvent(self,event):
        painter=QPainter(self);painter.fillRect(self.rect(),theme.color('surface'))
        if not self.peaks:
            painter.setPen(theme.color('dim'));painter.drawText(self.rect(),Qt.AlignCenter,tr('Loading…'));return
        start,end=self._x(self.a),self._x(self.b);selection=theme.color('accent');selection.setAlpha(45);painter.fillRect(QRectF(start,0,end-start,self.height()),selection)
        count=len(self.peaks);middle=self.height()/2
        for x in range(self.width()):
            first=min(count-1,int(self._t(x)/self.dur*count));last=max(first+1,min(count,int(self._t(x+1)/self.dur*count)))
            amplitude=max(1,max(self.peaks[first:last],default=0)*(middle-6))
            painter.setPen(theme.color('accent') if start<=x<=end else theme.color('faint'));painter.drawLine(QPointF(x,middle-amplitude),QPointF(x,middle+amplitude))
        painter.setPen(QPen(theme.color('accent'),2))
        for x in (start,end):painter.drawLine(QPointF(x,0),QPointF(x,self.height()))
        if self.head is not None:
            painter.setPen(theme.color('text'));painter.drawLine(QPointF(self._x(self.head),0),QPointF(self._x(self.head),self.height()))


class TrimWidget(QWidget):
    def __init__(self,path,max_len=40.):
        super().__init__();self.path=path;self.player=None;self._closed=False
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);self.view=WaveView(max_len);layout.addWidget(self.view)
        row=QHBoxLayout();self.play=QPushButton(tr('Play'));self.play.setEnabled(False);self.play.clicked.connect(self.toggle);row.addWidget(self.play)
        self.start_ed,self.end_ed=QLineEdit(),QLineEdit()
        for label,edit in [('Start',self.start_ed),('End',self.end_ed)]:
            edit.setFixedWidth(84);edit.setLayoutDirection(Qt.LeftToRight);edit.editingFinished.connect(self._typed);row.addWidget(QLabel(tr(label)));row.addWidget(edit)
        self.len_lbl=QLabel();row.addWidget(self.len_lbl);row.addStretch();layout.addLayout(row)
        self.hint=QLabel(tr('Drag the edges or the selection · scroll to zoom · up to {n} seconds',n=int(max_len)));self.hint.setWordWrap(True);self.hint.setObjectName('dim');layout.addWidget(self.hint)
        self.view.changed.connect(self._sync);self.view.seek.connect(lambda value:self._play_from(value) if self._playing() else None)
        try:
            from PySide6.QtMultimedia import QMediaPlayer,QAudioOutput
            self.player=QMediaPlayer(self);self.audio=QAudioOutput(self);self.player.setAudioOutput(self.audio);self.player.setSource(QUrl.fromLocalFile(str(Path(path).resolve())))
            self.player.positionChanged.connect(self._pos);self.player.playbackStateChanged.connect(self._label)
        except Exception as error:self.hint.setText(str(error))
        self._cancel=CancelToken();self._future=_POOL.submit(waveform_peaks,path,ffmpeg=engine.ffmpeg(),token=self._cancel);self._poll=QTimer(self);self._poll.setInterval(40);self._poll.timeout.connect(self._loaded);self._poll.start()
    def _loaded(self):
        if not self._future.done():return
        self._poll.stop()
        try:
            peaks,duration=self._future.result()
            if duration<=0:raise ValueError('The media duration is unavailable')
            self.view.set_data(peaks,duration);self.play.setEnabled(self.player is not None)
        except Exception as error:self.hint.setText(str(error))
    def _sync(self):
        self.start_ed.setText(f'{self.view.a:.3f}');self.end_ed.setText(f'{self.view.b:.3f}');self.len_lbl.setText(tr('{s} seconds',s=f'{self.view.b-self.view.a:.1f}'))
    def _typed(self):
        try:self.view.set_range(engine._secs(engine.parse_time(self.start_ed.text())),engine._secs(engine.parse_time(self.end_ed.text())),'a' if self.sender() is self.start_ed else 'b')
        except Exception:self._sync()
    def _playing(self):
        from PySide6.QtMultimedia import QMediaPlayer
        return self.player is not None and self.player.playbackState()==QMediaPlayer.PlayingState
    def _label(self,*args):self.play.setText(tr('Stop') if self._playing() else tr('Play'))
    def _play_from(self,value):self.player.setPosition(round(value*1000));self.player.play()
    def toggle(self):
        if self.player is None:return
        if self._playing():self.player.pause();self.view.head=None;self.view.update()
        else:self._play_from(self.view.a)
    def _pos(self,milliseconds):
        if not self._playing():return
        position=milliseconds/1000
        if position>=self.view.b or position<self.view.a-.5:self.player.pause();self.view.head=None
        else:self.view.head=position
        self.view.update()
    def value(self):
        if not self.view.dur:raise ValueError('Wait for the media waveform to load')
        return f'{self.view.a:.3f}-{self.view.b:.3f}'
    def stop(self):
        self._closed=True;self._poll.stop();self._cancel.cancel();self._future.cancel()
        if self.player:self.player.stop();self.player.setSource(QUrl())


def _frame(path):
    with tempfile.TemporaryDirectory(prefix='convertanny-frame-') as folder:
        image_path=Path(folder)/'frame.png'
        if not engine.preview_frame(path,image_path):raise ValueError('Could not preview this video')
        image=QImage(str(image_path)).copy()
    center=engine._face_center_x(path)
    return image,center


class CropPreview(QWidget):
    def __init__(self,path):
        super().__init__();self.setMinimumSize(560,250);self.setCursor(Qt.OpenHandCursor)
        self.img=None;self.ratio=9/16;self.cx=.5;self.moved=False;self._drag=None
        self._future=_POOL.submit(_frame,path);self._timer=QTimer(self);self._timer.setInterval(40);self._timer.timeout.connect(self._loaded);self._timer.start();self.error=''
    def _loaded(self):
        if not self._future.done():return
        self._timer.stop()
        try:
            self.img,center=self._future.result()
            if center is not None and not self.moved:self.cx=max(0,min(1,float(center)))
        except Exception as error:self.error=str(error)
        self.update()
    def set_shape(self,label):
        width,height=map(int,str(label).split()[0].split(':'))
        if width<=0 or height<=0:raise ValueError('Invalid crop ratio')
        self.ratio=width/height;self.update()
    def _rects(self):
        width,height=(self.img.width(),self.img.height()) if self.img is not None else (16,9)
        scale=min(self.width()/max(1,width),self.height()/max(1,height));width,height=width*scale,height*scale
        picture=QRectF((self.width()-width)/2,(self.height()-height)/2,width,height)
        crop_width,crop_height=(height*self.ratio,height) if width/height>self.ratio else (width,width/self.ratio)
        return picture,QRectF(picture.x()+max(0,min(width-crop_width,width*self.cx-crop_width/2)),picture.y()+(height-crop_height)/2,crop_width,crop_height)
    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHints(QPainter.Antialiasing|QPainter.SmoothPixmapTransform);painter.fillRect(self.rect(),theme.color('surface'))
        if self.img is None:painter.setPen(theme.color('dim'));painter.drawText(self.rect(),Qt.AlignCenter,self.error or tr('Loading…'));return
        picture,crop=self._rects();painter.drawImage(picture,self.img);outside=QPainterPath();outside.addRect(picture);inside=QPainterPath();inside.addRect(crop)
        painter.fillPath(outside.subtracted(inside),QColor(0,0,0,150));painter.setPen(QPen(theme.color('accent'),2));painter.setBrush(Qt.NoBrush);painter.drawRect(crop)
        painter.setPen(QPen(QColor(255,255,255,70),1))
        for fraction in (1/3,2/3):
            x,y=crop.x()+crop.width()*fraction,crop.y()+crop.height()*fraction;painter.drawLine(QPointF(x,crop.top()),QPointF(x,crop.bottom()));painter.drawLine(QPointF(crop.left(),y),QPointF(crop.right(),y))
    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton and self.img is not None:self._drag=(event.position().x(),self.cx)
    def mouseMoveEvent(self,event):
        if self._drag is None:return
        picture,crop=self._rects();half=crop.width()/2/picture.width();self.cx=max(half,min(1-half,self._drag[1]+(event.position().x()-self._drag[0])/picture.width()));self.moved=True;self.update()
    def mouseReleaseEvent(self,event):self._drag=None
    def value(self):
        if self.img is None:return ''
        picture,crop=self._rects();return f'{(crop.center().x()-picture.x())/picture.width():.4f}'
    def stop(self):self._timer.stop();self._future.cancel()
