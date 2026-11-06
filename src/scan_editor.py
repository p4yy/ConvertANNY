"""ConvertANNY scanner corner controls and asynchronous appearance previews."""
import json
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import Qt,QTimer,QPointF,QRectF,QSettings,QSize
from PySide6.QtGui import QPainter,QPen,QColor,QPainterPath,QPolygonF,QPixmap,QIcon
from PySide6.QtWidgets import QWidget,QHBoxLayout,QVBoxLayout,QLabel,QPushButton,QToolButton,QButtonGroup
import engine,theme
from crop_canvas import pil_to_qimage
from i18n import tr

_POOL=ThreadPoolExecutor(max_workers=2,thread_name_prefix='ConvertANNY-scan')


def _load(path):
    with engine.open_image(path) as opened:image=opened.convert('RGB')
    image.thumbnail((1400,1400));return image,engine.detect_document(image)


def _previews(image,points,rotation,version):
    image=image.copy();image.thumbnail((700,700));results={}
    for look in engine.SCAN_LOOKS:
        result=engine.straighten(image,points,look)
        if rotation:result=result.rotate(-rotation,expand=True)
        results[look]=result
    return version,results


class _CornerView(QWidget):
    def __init__(self,editor):
        super().__init__();self.editor=editor;self.setFixedSize(470,560);self.setMouseTracking(True)
    def paintEvent(self,event):self.editor._paint()
    def mousePressEvent(self,event):self.editor._press(event)
    def mouseMoveEvent(self,event):self.editor._move(event)
    def mouseReleaseEvent(self,event):self.editor.drag=None;self.update()


class CornerPicker(QWidget):
    LOOKS=engine.SCAN_LOOKS
    def __init__(self,path):
        super().__init__();self.path=path;self.pil=None;self.img=None;self.pts=None;self.found=None;self.rot=0;self.drag=None
        self._closed=False;self._version=0;self._results={};self._loading=True;self._pending=False
        self.settings=QSettings('ConvertANNY','ConvertANNY');self.look=str(self.settings.value('scan_look',self.LOOKS[0]))
        if self.look not in self.LOOKS:self.look=self.LOOKS[0]
        layout=QHBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(18)
        left=QVBoxLayout();self.view=_CornerView(self);left.addWidget(self.view)
        self.hint=QLabel(tr('Finding the page…'));self.hint.setWordWrap(True);self.hint.setObjectName('dim');left.addWidget(self.hint)
        buttons=QHBoxLayout();self.tool_btns={}
        for key,label,callback in [('left','Left',lambda:self._rotate(-90)),('right','Right',lambda:self._rotate(90)),
             ('auto','Find the page',lambda:self._set(self.found)),('all','Whole picture',lambda:self._set([[0,0],[1,0],[1,1],[0,1]]))]:
            button=QPushButton(tr(label));button.clicked.connect(callback);buttons.addWidget(button);self.tool_btns[key]=button
        self.tool_btns['auto'].setEnabled(False);left.addLayout(buttons);layout.addLayout(left)
        right=QVBoxLayout();right.addWidget(QLabel(tr('Preview')));self.prev=QLabel();self.prev.setFixedSize(300,400);self.prev.setAlignment(Qt.AlignCenter);right.addWidget(self.prev)
        right.addWidget(QLabel(tr('Look')));choices=QHBoxLayout();self.group=QButtonGroup(self);self.chips={}
        labels={'Clean document':'Clean','Original colours':'Original','Black & white':'B&W','Grayscale':'Gray'}
        for look in self.LOOKS:
            button=QToolButton();button.setCheckable(True);button.setChecked(look==self.look);button.setText(tr(labels.get(look,look)));button.setToolTip(tr(look))
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon);button.setIconSize(QSize(58,76));button.clicked.connect(lambda checked=False,look=look:self._set_look(look))
            self.group.addButton(button);self.chips[look]=button;choices.addWidget(button)
        right.addLayout(choices);right.addStretch();layout.addLayout(right)
        self._future=_POOL.submit(_load,path)
        self._poll=QTimer(self);self._poll.setInterval(40);self._poll.timeout.connect(self._update);self._poll.start()
        self._debounce=QTimer(self);self._debounce.setSingleShot(True);self._debounce.setInterval(150);self._debounce.timeout.connect(self._render)

    def _update(self):
        if self._closed or self._future is None or not self._future.done():return
        future=self._future;self._future=None
        try:
            if self._loading:
                self.pil,self.found=future.result();self._loading=False
                self.img=pil_to_qimage(self.pil).scaled(442,532,Qt.KeepAspectRatio,Qt.SmoothTransformation)
                self.pts=[list(point) for point in (self.found or [[.04,.04],[.96,.04],[.96,.96],[.04,.96]])]
                self.tool_btns['auto'].setEnabled(self.found is not None);self.hint.setText(tr('Drag the corners onto the corners of the page.'))
                self.view.update();self._render();return
            version,results=future.result()
            if version!=self._version:self._render();return
            self._results=results
            for look,image in results.items():
                pixmap=QPixmap.fromImage(pil_to_qimage(image));self.chips[look].setIcon(QIcon(pixmap))
            self._show_preview()
        except Exception as error:self.hint.setText(str(error));self._loading=False
        if self._pending:self._pending=False;self._render()
    def _changed(self):self._version+=1;self.view.update();self._debounce.start()
    def _render(self):
        if self._closed or self.pil is None or self.pts is None:return
        if self._future is not None:self._pending=True;return
        self._future=_POOL.submit(_previews,self.pil,[list(point) for point in self.pts],self.rot,self._version)
    def _show_preview(self):
        if self.look in self._results:self.prev.setPixmap(QPixmap.fromImage(pil_to_qimage(self._results[self.look])).scaled(284,384,Qt.KeepAspectRatio,Qt.SmoothTransformation))
    def _set(self,points):
        if points is not None and self.pil is not None:self.pts=[list(point) for point in points];self._changed()
    def _rotate(self,degrees):self.rot=(self.rot+degrees)%360;self._changed()
    def _set_look(self,look):self.look=look;self.settings.setValue('scan_look',look);self._show_preview()
    def _origin(self):return QPointF((470-self.img.width())/2,(560-self.img.height())/2)
    def _to_view(self,point):return self._origin()+QPointF(point[0]*(self.img.width()-1),point[1]*(self.img.height()-1))
    def _hit(self,position):
        if self.img is None:return None
        for index,point in enumerate(self.pts):
            if (self._to_view(point)-position).manhattanLength()<24:return index
        for index in range(4):
            middle=(self._to_view(self.pts[index])+self._to_view(self.pts[(index+1)%4]))/2
            if (middle-position).manhattanLength()<18:return ('side',index)
        return None
    def _press(self,event):
        if event.button()==Qt.LeftButton:self.drag=self._hit(event.position());self._last=event.position();self.view.update()
    def _move(self,event):
        if self.img is None:return
        if self.drag is None:
            self.view.setCursor(Qt.OpenHandCursor if self._hit(event.position()) is not None else Qt.ArrowCursor);return
        position=event.position();origin=self._origin()
        if isinstance(self.drag,int):
            self.pts[self.drag]=[max(0,min(1,(position.x()-origin.x())/(self.img.width()-1))),max(0,min(1,(position.y()-origin.y())/(self.img.height()-1)))]
        else:
            delta=position-self._last
            for index in (self.drag[1],(self.drag[1]+1)%4):
                point=self.pts[index];point[0]=max(0,min(1,point[0]+delta.x()/(self.img.width()-1)));point[1]=max(0,min(1,point[1]+delta.y()/(self.img.height()-1)))
        self._last=position;self._changed()
    def _paint(self):
        painter=QPainter(self.view);painter.setRenderHints(QPainter.Antialiasing|QPainter.SmoothPixmapTransform);painter.fillRect(self.view.rect(),theme.color('surface'))
        if self.img is None:
            painter.setPen(theme.color('dim'));painter.drawText(self.view.rect(),Qt.AlignCenter,tr('Finding the page…'));return
        origin=self._origin();painter.drawImage(origin,self.img)
        polygon=QPolygonF([self._to_view(point) for point in self.pts]);outside=QPainterPath();outside.addRect(QRectF(origin.x(),origin.y(),self.img.width(),self.img.height()))
        inside=QPainterPath();inside.addPolygon(polygon);inside.closeSubpath();painter.fillPath(outside.subtracted(inside),QColor(0,0,0,130))
        painter.setPen(QPen(theme.color('accent'),2));painter.setBrush(Qt.NoBrush);painter.drawPolygon(polygon)
        painter.setBrush(theme.color('accent'));painter.setPen(QPen(Qt.white,2))
        for point in polygon:painter.drawEllipse(point,9,9)
        for index in range(4):painter.drawEllipse((polygon[index]+polygon[(index+1)%4])/2,5,5)
        if isinstance(self.drag,int):
            corner=self._to_view(self.pts[self.drag]);lens=QRectF(330,18,116,116);clip=QPainterPath();clip.addEllipse(lens)
            painter.save();painter.setClipPath(clip);painter.fillRect(lens,Qt.black)
            painter.drawImage(lens,self.img,QRectF(corner.x()-origin.x()-19,corner.y()-origin.y()-19,38,38));painter.restore()
            painter.setBrush(Qt.NoBrush);painter.setPen(QPen(Qt.white,2));painter.drawEllipse(lens)
            painter.setPen(QPen(theme.color('accent'),1));painter.drawLine(QPointF(376,76),QPointF(400,76));painter.drawLine(QPointF(388,64),QPointF(388,88))
    def value(self):return json.dumps(dict(corners=self.pts,look=self.look,rotate=self.rot)) if self.pts is not None else ''
    def stop(self):
        self._closed=True;self._poll.stop();self._debounce.stop()
        if self._future is not None:self._future.cancel()
