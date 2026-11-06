"""ConvertANNY signature drawing, preparation and page placement."""
from __future__ import annotations
import json
from pathlib import Path
from PySide6.QtCore import Qt,QPointF,QRectF,QSettings
from PySide6.QtGui import QImage,QPainter,QPainterPath,QPen,QColor
from PySide6.QtWidgets import (QWidget,QDialog,QVBoxLayout,QHBoxLayout,QPushButton,QLabel,
 QDialogButtonBox,QRadioButton,QButtonGroup,QSpinBox,QFileDialog)
import pymupdf
import engine,theme
from i18n import tr


def _signature_file():
    return Path(engine.models_dir()).parent/'signature.png'


def _clean_signature(source,destination):
    from PIL import Image,ImageChops
    from uuid import uuid4
    with engine.open_image(source) as opened:
        image=opened.convert('RGBA')
    image.thumbnail((1400,1400))
    existing=image.getchannel('A')
    if existing.getextrema()[0]>=250:
        mask=image.convert('L').point(lambda value:max(0,min(255,round((200-value)*255/80))))
        image.putalpha(ImageChops.multiply(existing,mask))
    bounds=image.getbbox()
    if bounds is None:raise ValueError('No signature ink found in this image')
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    temporary=destination.with_name('.signature-'+uuid4().hex+'.png')
    try:
        image.crop(bounds).save(temporary,format='PNG');temporary.replace(destination)
    finally:temporary.unlink(missing_ok=True)
    return destination


class _InkCanvas(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);self.setMinimumSize(520,200);self.setCursor(Qt.CrossCursor)
        self.strokes=[];self._drawing=False
    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton:self.strokes.append([event.position()]);self._drawing=True;self.update()
    def mouseMoveEvent(self,event):
        if self._drawing:self.strokes[-1].append(event.position());self.update()
    def mouseReleaseEvent(self,event):self._drawing=False
    def draw(self,painter):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor('#141e5a'),3.2,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin))
        for points in self.strokes:
            if not points:continue
            path=QPainterPath(points[0])
            for point in points[1:]:path.lineTo(point)
            if len(points)==1:painter.drawPoint(points[0])
            else:painter.drawPath(path)
    def paintEvent(self,event):
        painter=QPainter(self);painter.fillRect(self.rect(),Qt.white)
        painter.setPen(QPen(QColor('#c8c8cd'),1,Qt.DashLine))
        painter.drawLine(QPointF(20,self.height()*.72),QPointF(self.width()-20,self.height()*.72));self.draw(painter)


class DrawPad(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent,Qt.WindowStaysOnTopHint);self.setWindowTitle('ConvertANNY · '+tr('Draw your signature'))
        layout=QVBoxLayout(self);self.canvas=_InkCanvas();layout.addWidget(self.canvas)
        row=QHBoxLayout();clear=QPushButton(tr('Clear'));clear.clicked.connect(self._clear);row.addWidget(clear);row.addStretch()
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(tr('Use this signature'));buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject)
        row.addWidget(buttons);layout.addLayout(row)
    def _clear(self):self.canvas.strokes.clear();self.canvas.update()
    def save(self,destination):
        if not any(len(stroke)>1 for stroke in self.canvas.strokes):return None
        image=QImage(self.canvas.width()*3,self.canvas.height()*3,QImage.Format_ARGB32);image.fill(Qt.transparent)
        painter=QPainter(image);painter.scale(3,3);self.canvas.draw(painter);painter.end()
        destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
        import tempfile
        with tempfile.TemporaryDirectory(prefix='convertanny-signature-') as folder:
            source=Path(folder)/'ink.png'
            if not image.save(str(source)):raise OSError('Could not save the signature')
            return _clean_signature(source,destination)


class _PlacementView(QWidget):
    def __init__(self,owner):
        super().__init__();self.owner=owner;self.setMinimumSize(470,360);self.setMouseTracking(True)
    def paintEvent(self,event):self.owner._paint()
    def mousePressEvent(self,event):self.owner._press(event)
    def mouseMoveEvent(self,event):self.owner._move(event)
    def mouseReleaseEvent(self,event):self.owner._drag=None


class SignPlacer(QWidget):
    def __init__(self,paths):
        super().__init__();self.settings=QSettings('ConvertANNY','ConvertANNY')
        pdf=next(path for path in paths if engine.EXT_CATEGORY.get(engine.ext_of(path))=='pdf')
        self.doc=pymupdf.open(pdf)
        if self.doc.needs_pass or not self.doc.page_count:
            self.doc.close();raise ValueError('Choose an unlocked PDF with at least one page')
        self.pages=self.doc.page_count;self.page_i=self.pages-1
        self.shared=[.58,.78,.90,.88];self.places={};self.mode='this';self._drag=None
        self.sig_path=None;self.sig_img=None;self._page_img=None
        layout=QHBoxLayout(self);layout.setContentsMargins(0,0,0,0);self.view=_PlacementView(self);layout.addWidget(self.view,1)
        controls=QVBoxLayout();layout.addLayout(controls)
        navigation=QHBoxLayout();self.prev_b=QPushButton('◀');self.next_b=QPushButton('▶');self.page_lbl=QLabel()
        self.prev_b.clicked.connect(lambda:self._go(-1));self.next_b.clicked.connect(lambda:self._go(1))
        navigation.addWidget(self.prev_b);navigation.addWidget(self.page_lbl,1);navigation.addWidget(self.next_b);controls.addLayout(navigation)
        self.r_from,self.r_to=QSpinBox(),QSpinBox()
        for control,value in ((self.r_from,1),(self.r_to,self.pages)):control.setRange(1,self.pages);control.setValue(value)
        self.mode_group=QButtonGroup(self);self.modes={}
        for key,label in [('this','Only the page shown'),('all','All pages'),('range','Pages from'),('pick','Pages I click')]:
            button=QRadioButton(tr(label));self.mode_group.addButton(button);self.modes[key]=button;controls.addWidget(button)
            button.toggled.connect(lambda on,key=key:self._set_mode(key) if on else None)
            if key=='range':
                row=QHBoxLayout();row.addWidget(self.r_from);row.addWidget(QLabel(tr('to')));row.addWidget(self.r_to);controls.addLayout(row)
        self.r_from.valueChanged.connect(self._range_changed);self.r_to.valueChanged.connect(self._range_changed)
        self.signed_lbl=QLabel();self.signed_lbl.setWordWrap(True);controls.addWidget(self.signed_lbl)
        for label,callback in [('Draw signature…',self._draw_new),('Use a picture…',self._pick),('Delete signature',self._delete_sig)]:
            button=QPushButton(tr(label));button.clicked.connect(callback);controls.addWidget(button)
        hint=QLabel(tr('Drag the signature into place and drag its corner to make it bigger or smaller. It is remembered for next time.'))
        hint.setWordWrap(True);controls.addWidget(hint);self.error=QLabel();self.error.setWordWrap(True);controls.addWidget(self.error);controls.addStretch()
        self.setAcceptDrops(True);self._go(0)
        mode=str(self.settings.value('sign_mode','this'));self.modes.get(mode,self.modes['this']).setChecked(True)
        source=next((path for path in paths if engine.EXT_CATEGORY.get(engine.ext_of(path))=='image'),None)
        if source:
            try:self._set_sig(_clean_signature(source,_signature_file()))
            except Exception as error:self.error.setText(str(error))
        elif _signature_file().is_file():self._set_sig(_signature_file())

    @property
    def box(self):
        if self.mode=='pick':return self.places.get(self.page_i)
        if self.mode=='range' and self.page_i not in self.signed_pages():return None
        return self.shared
    @box.setter
    def box(self,rectangle):
        if self.mode=='pick':self.places[self.page_i]=list(rectangle)
        else:self.shared=list(rectangle)

    def _go(self,step):
        self.page_i=max(0,min(self.pages-1,self.page_i+step));page=self.doc[self.page_i]
        pixels=page.get_pixmap(matrix=pymupdf.Matrix(900/max(page.rect.width,page.rect.height),900/max(page.rect.width,page.rect.height)),alpha=False)
        self._page_img=QImage(pixels.samples,pixels.width,pixels.height,pixels.stride,QImage.Format_RGB888).copy()
        self.page_lbl.setText(tr('Page {i} of {n}',i=self.page_i+1,n=self.pages));self.prev_b.setEnabled(self.page_i>0);self.next_b.setEnabled(self.page_i<self.pages-1);self._status();self.view.update()

    def _set_mode(self,key):
        self.mode=key;self.settings.setValue('sign_mode',key)
        if key=='pick' and not self.places:self.places[self.page_i]=list(self.shared)
        self.r_from.setEnabled(key=='range');self.r_to.setEnabled(key=='range');self._status();self.view.update()
    def _range_changed(self):
        if self.r_from.value()>self.r_to.value():self.r_to.setValue(self.r_from.value())
        self.modes['range'].setChecked(True);self._status();self.view.update()
    def signed_pages(self):
        if self.mode=='all':return list(range(self.pages))
        if self.mode=='range':return list(range(self.r_from.value()-1,self.r_to.value()))
        if self.mode=='pick':return sorted(self.places)
        return [self.page_i]
    def _status(self):
        pages=self.signed_pages()
        self.signed_lbl.setText(tr('Signed pages: {list}',list=', '.join(str(page+1) for page in pages[:12])))

    def _page_rect(self):
        image=self._page_img;scale=min(max(1,self.view.width()-8)/image.width(),max(1,self.view.height()-8)/image.height())
        width,height=image.width()*scale,image.height()*scale
        return QRectF((self.view.width()-width)/2,(self.view.height()-height)/2,width,height)
    def _sig_rect(self):
        page=self._page_rect();x,y,right,bottom=self.box
        return QRectF(page.x()+x*page.width(),page.y()+y*page.height(),(right-x)*page.width(),(bottom-y)*page.height())
    def _paint(self):
        painter=QPainter(self.view);painter.setRenderHints(QPainter.Antialiasing|QPainter.SmoothPixmapTransform)
        painter.fillRect(self.view.rect(),theme.color('canvas'));painter.drawImage(self._page_rect(),self._page_img)
        if self.sig_img is not None and self.box is not None:
            rectangle=self._sig_rect();painter.drawImage(rectangle,self.sig_img)
            painter.setPen(QPen(theme.color('accent'),1.5,Qt.DashLine));painter.setBrush(Qt.NoBrush);painter.drawRect(rectangle)
            painter.setBrush(theme.color('accent'));painter.drawEllipse(rectangle.bottomRight(),6,6)
    def _press(self,event):
        if self.sig_img is None:return
        if event.button()==Qt.RightButton:
            if self.mode=='pick' and self.box is not None and self._sig_rect().contains(event.position()):self.places.pop(self.page_i,None);self._status();self.view.update()
            return
        if event.button()!=Qt.LeftButton:return
        if self.box is None:
            if self.mode!='pick':return
            page=self._page_rect();width=self.shared[2]-self.shared[0];height=self.shared[3]-self.shared[1]
            x=min(max(0,(event.position().x()-page.x())/page.width()-width/2),1-width)
            y=min(max(0,(event.position().y()-page.y())/page.height()-height/2),1-height)
            self.places[self.page_i]=[x,y,x+width,y+height];self._status();self.view.update()
        rectangle=self._sig_rect();position=event.position()
        if (position-rectangle.bottomRight()).manhattanLength()<16:self._drag=('resize',position,list(self.box))
        elif rectangle.contains(position):self._drag=('move',position,list(self.box))
    def _move(self,event):
        if self._drag is None:return
        kind,start,original=self._drag;page=self._page_rect();dx=(event.position().x()-start.x())/page.width();dy=(event.position().y()-start.y())/page.height()
        x,y,right,bottom=original;width,height=right-x,bottom-y
        if kind=='move':
            x=min(max(0,x+dx),1-width);y=min(max(0,y+dy),1-height)
        else:
            ratio=self.sig_img.height()/self.sig_img.width()*page.width()/page.height()
            width=min(max(.05,width+dx),1-x,(1-y)/ratio);height=width*ratio
        self.box=[x,y,x+width,y+height];self.view.update()
    def _set_sig(self,path):
        image=QImage(str(path))
        if image.isNull():raise ValueError('Could not open the signature image')
        first_signature=self.sig_img is None
        self.sig_path=Path(path);self.sig_img=image
        width=self.shared[2]-self.shared[0];height=width*image.height()/image.width()*self._page_img.width()/self._page_img.height()
        height=min(height,1);width=height*image.width()/image.height()*self._page_img.height()/self._page_img.width()
        x=min(self.shared[0],1-width);y=min(self.shared[1],1-height);self.shared=[x,y,x+width,y+height]
        if first_signature:self.places={page:list(self.shared) for page in self.places}
        self.view.update()
    def _draw_new(self):
        pad=DrawPad(self)
        if pad.exec()==QDialog.Accepted:
            try:
                path=pad.save(_signature_file())
                if path:self._set_sig(path)
            except Exception as error:self.error.setText(str(error))
    def _pick(self):
        path,_=QFileDialog.getOpenFileName(self,tr('Use a picture…'),str(Path.home()),'Images (*.png *.jpg *.jpeg *.webp *.bmp *.heic)')
        if path:
            try:self._set_sig(_clean_signature(path,_signature_file()))
            except Exception as error:self.error.setText(str(error))
    def _delete_sig(self):
        _signature_file().unlink(missing_ok=True);self.sig_path=None;self.sig_img=None;self.view.update()
    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls() or event.mimeData().hasImage():event.acceptProposedAction()
    def dragMoveEvent(self,event):self.dragEnterEvent(event)
    def dropEvent(self,event):
        try:
            path=next((url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()),None)
            if path:self._set_sig(_clean_signature(path,_signature_file()));event.acceptProposedAction()
            elif event.mimeData().hasImage():
                import tempfile
                with tempfile.TemporaryDirectory(prefix='convertanny-signature-drop-') as folder:
                    source=Path(folder)/'dropped.png';QImage(event.mimeData().imageData()).save(str(source));self._set_sig(_clean_signature(source,_signature_file()))
                event.acceptProposedAction()
        except Exception as error:self.error.setText(str(error))
    def value(self):
        if self.sig_path is None:return ''
        places=[dict(page=page,rect=self.places[page] if self.mode=='pick' else self.shared) for page in self.signed_pages()]
        return json.dumps(dict(sig=str(self.sig_path),places=places)) if places else ''
    def stop(self):
        if not self.doc.is_closed:self.doc.close()
