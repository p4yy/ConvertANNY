"""ConvertANNY crop interaction in source-image coordinates."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, QSizeF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget, QSizePolicy
import theme


def pil_to_qimage(image):
    pixels = image.convert("RGBA")
    return QImage(pixels.tobytes(),pixels.width,pixels.height,pixels.width*4,QImage.Format_RGBA8888).copy()


class CropCanvas(QWidget):
    changed = Signal()
    _POSITIONS = {"tl":(0,0),"t":(.5,0),"tr":(1,0),"r":(1,.5),
                  "br":(1,1),"b":(.5,1),"bl":(0,1),"l":(0,.5)}

    def __init__(self):
        super().__init__()
        self.setMinimumSize(520,380)
        self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.img = None
        self.full = QSize(1,1)
        self.crop = QRectF(0,0,1,1)
        self.aspect = None
        self._gesture = None
        self._raster = None

    def set_image(self, qimg, full, keep_crop=False):
        self.img = qimg
        self.full = QSize(full)
        self._raster = None
        if not keep_crop:
            self.crop = QRectF(0,0,full.width(),full.height())
            self.apply_aspect()
        else:
            self.set_crop(self.crop)

    def _view(self):
        if self.img is None or self.full.isEmpty():
            return QRectF()
        scale = min(max(1,self.width()-36)/self.full.width(),max(1,self.height()-36)/self.full.height())
        size = QSize(round(self.full.width()*scale),round(self.full.height()*scale))
        return QRectF((self.width()-size.width())/2,(self.height()-size.height())/2,size.width(),size.height())

    def to_image(self, point):
        view = self._view()
        if view.isEmpty():
            return QPointF()
        return QPointF((point.x()-view.x())*self.full.width()/view.width(),
                       (point.y()-view.y())*self.full.height()/view.height())

    def to_widget(self, rectangle):
        view = self._view()
        sx,sy = view.width()/max(1,self.full.width()),view.height()/max(1,self.full.height())
        return QRectF(view.x()+rectangle.x()*sx,view.y()+rectangle.y()*sy,rectangle.width()*sx,rectangle.height()*sy)

    def set_crop(self, rectangle):
        rectangle = rectangle.normalized()
        width = min(max(1,rectangle.width()),self.full.width())
        height = min(max(1,rectangle.height()),self.full.height())
        self.crop = QRectF(min(max(0,rectangle.x()),self.full.width()-width),
                           min(max(0,rectangle.y()),self.full.height()-height),width,height)
        self.changed.emit()
        self.update()

    def set_aspect(self, aspect):
        self.aspect = float(aspect) if aspect and float(aspect)>0 else None
        self.apply_aspect()

    def apply_aspect(self):
        candidate = QRectF(self.crop)
        if self.aspect:
            center = candidate.center()
            width = min(candidate.width(),candidate.height()*self.aspect)
            candidate.setSize(QSizeF(width,width/self.aspect))
            candidate.moveCenter(center)
        self.set_crop(candidate)

    def _handles(self):
        view = self.to_widget(self.crop)
        return {name:QPointF(view.x()+x*view.width(),view.y()+y*view.height()) for name,(x,y) in self._POSITIONS.items()}

    def _hit(self, point):
        for name,handle in self._handles().items():
            if abs(point.x()-handle.x())<=11 and abs(point.y()-handle.y())<=11:
                return name
        if self.to_widget(self.crop).contains(point):
            return 'move'
        return 'new' if self._view().contains(point) else None

    def mousePressEvent(self, event):
        if event.button()!=Qt.LeftButton or self.img is None:
            return
        mode = self._hit(event.position())
        if mode:
            point = self.to_image(event.position())
            self._gesture = (mode,point,QRectF(self.crop))
            event.accept()

    def mouseMoveEvent(self, event):
        if self._gesture is None:
            mode = self._hit(event.position())
            cursor = Qt.ArrowCursor
            if mode in ('tl','br'):cursor = Qt.SizeFDiagCursor
            elif mode in ('tr','bl'):cursor = Qt.SizeBDiagCursor
            elif mode in ('l','r'):cursor = Qt.SizeHorCursor
            elif mode in ('t','b'):cursor = Qt.SizeVerCursor
            elif mode=='move':cursor = Qt.SizeAllCursor
            elif mode=='new':cursor = Qt.CrossCursor
            self.setCursor(cursor)
            return
        mode,start,original = self._gesture
        point = self.to_image(event.position())
        point.setX(min(self.full.width(),max(0,point.x())))
        point.setY(min(self.full.height(),max(0,point.y())))
        if mode=='move':
            moved = QRectF(original)
            moved.translate(point-start)
            self.set_crop(moved)
            return
        if mode=='new':
            anchor = start
            horizontal = 1 if point.x()>=start.x() else -1
            vertical = 1 if point.y()>=start.y() else -1
        else:
            horizontal = -1 if 'l' in mode else 1
            vertical = -1 if 't' in mode else 1
            anchor = QPointF(original.right() if 'l' in mode else original.left(),original.bottom() if 't' in mode else original.top())
        width = abs(point.x()-anchor.x()) if mode=='new' or 'l' in mode or 'r' in mode else original.width()
        height = abs(point.y()-anchor.y()) if mode=='new' or 't' in mode or 'b' in mode else original.height()
        if mode != 'new':
            if 'l' in mode or 'r' in mode:
                width = max(min(8,self.full.width()),horizontal*(point.x()-anchor.x()))
            if 't' in mode or 'b' in mode:
                height = max(min(8,self.full.height()),vertical*(point.y()-anchor.y()))
        if self.aspect:
            if mode in ('t','b'):width = height*self.aspect
            else:height = width/self.aspect
            available_width = anchor.x() if horizontal<0 else self.full.width()-anchor.x()
            available_height = anchor.y() if vertical<0 else self.full.height()-anchor.y()
            factor = min(1,available_width/max(1,width),available_height/max(1,height))
            width,height = width*factor,height*factor
        if width>=min(8,self.full.width()) and height>=min(8,self.full.height()):
            self.set_crop(QRectF(anchor.x()-width if horizontal<0 else anchor.x(),
                                 anchor.y()-height if vertical<0 else anchor.y(),width,height))

    def mouseReleaseEvent(self, event):
        self._gesture = None
        event.accept()

    def mouseDoubleClickEvent(self, event):
        self.crop = QRectF(0,0,self.full.width(),self.full.height())
        self.apply_aspect()

    def resizeEvent(self, event):
        self._raster = None
        super().resizeEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing|QPainter.SmoothPixmapTransform)
        painter.fillRect(self.rect(),theme.color('canvas'))
        if self.img is None:
            return
        view = self._view()
        key = (round(view.width()),round(view.height()),self.devicePixelRatioF(),theme.mode())
        if self._raster is None or self._raster[0]!=key:
            ratio = self.devicePixelRatioF()
            pixels = QPixmap(max(1,round(view.width()*ratio)),max(1,round(view.height()*ratio)))
            pixels.setDevicePixelRatio(ratio)
            pixels.fill(theme.color('check_b'))
            background = QPainter(pixels)
            for y in range(0,round(view.height())+10,10):
                for x in range(0,round(view.width())+10,10):
                    if (x//10+y//10)%2:
                        background.fillRect(x,y,10,10,theme.color('check_a'))
            background.setRenderHint(QPainter.SmoothPixmapTransform)
            background.drawImage(QRectF(0,0,view.width(),view.height()),self.img)
            background.end()
            self._raster = (key,pixels)
        painter.drawPixmap(view.topLeft(),self._raster[1])
        box = self.to_widget(self.crop)
        outside = QPainterPath();outside.addRect(view)
        inside = QPainterPath();inside.addRect(box)
        painter.fillPath(outside.subtracted(inside),QColor(0,0,0,150))
        painter.setPen(QPen(QColor(255,255,255,70),1))
        for fraction in (1/3,2/3):
            x,y = box.x()+box.width()*fraction,box.y()+box.height()*fraction
            painter.drawLine(QPointF(x,box.top()),QPointF(x,box.bottom()))
            painter.drawLine(QPointF(box.left(),y),QPointF(box.right(),y))
        painter.setPen(QPen(QColor('white'),1.5));painter.setBrush(Qt.NoBrush);painter.drawRect(box)
        painter.setPen(QPen(theme.color('border'),1));painter.setBrush(theme.color('accent'))
        for point in self._handles().values():
            painter.drawRoundedRect(QRectF(point.x()-5,point.y()-5,10,10),3,3)
