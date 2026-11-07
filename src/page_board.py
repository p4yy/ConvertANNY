"""ConvertANNY PDF and image page arrangement using Qt's item view."""
from __future__ import annotations

import json
from pathlib import Path
from PySide6.QtCore import Qt,QSize,QTimer
from PySide6.QtGui import QIcon,QImage,QPixmap,QTransform
from PySide6.QtWidgets import (QWidget,QListWidget,QListWidgetItem,QAbstractItemView,QVBoxLayout,
 QHBoxLayout,QPushButton,QLabel,QFileDialog)
import engine
from crop_canvas import pil_to_qimage
from i18n import tr


class _PageList(QListWidget):
    def __init__(self,board):
        super().__init__(board)
        self.board=board
        self.setViewMode(QListWidget.IconMode);self.setFlow(QListWidget.LeftToRight)
        self.setWrapping(True);self.setResizeMode(QListWidget.Adjust)
        self.setMovement(QListWidget.Snap);self.setGridSize(QSize(146,166));self.setIconSize(QSize(128,128))
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True);self.setAcceptDrops(True);self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDrop);self.setDefaultDropAction(Qt.MoveAction)
        self.setSpacing(6)

    def dragEnterEvent(self,event):
        if event.source() is self or event.mimeData().hasUrls():event.acceptProposedAction()
        else:event.ignore()

    def dragMoveEvent(self,event):
        if event.source() is self or event.mimeData().hasUrls():event.acceptProposedAction()
        else:event.ignore()

    def dropEvent(self,event):
        target=self.itemAt(event.position().toPoint())
        index=self.row(target) if target is not None else self.count()
        if event.source() is self:
            rows=sorted(self.row(item) for item in self.selectedItems())
            self.board.move_pages(rows,index)
            event.setDropAction(Qt.MoveAction);event.accept()
        elif event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():index+=self.board._add_file(url.toLocalFile(),index)
            event.acceptProposedAction()
        else:event.ignore()

    def keyPressEvent(self,event):
        if event.key() in (Qt.Key_Delete,Qt.Key_Backspace):self.board._delete()
        else:super().keyPressEvent(event)


class PageBoard(QWidget):
    def __init__(self,paths):
        super().__init__()
        self.sources=[];self.docs={};self._thumbnails={};self._stopped=False
        self.list=_PageList(self)
        self.count=QLabel();self.error=QLabel();self.error.setWordWrap(True);self.error.setObjectName('dim')
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.addWidget(self.list,1)
        self.list.setMinimumSize(640,380)
        toolbar=QHBoxLayout()
        actions=[('⟲  '+tr('Turn left'),lambda:self._turn(-90)),('⟳  '+tr('Turn right'),lambda:self._turn(90)),
                 ('✕  '+tr('Delete'),self._delete),('＋  '+tr('Add files…'),self._add_dialog)]
        for label,action in actions:
            button=QPushButton(label);button.clicked.connect(action);toolbar.addWidget(button)
        toolbar.addStretch();toolbar.addWidget(self.count);layout.addLayout(toolbar);layout.addWidget(self.error)
        hint=QLabel(tr('Drag pages to change the order · Ctrl or Shift picks several · Delete removes them · drop PDFs or pictures here to add their pages'))
        hint.setWordWrap(True);hint.setObjectName('dim');layout.addWidget(hint)
        self._timer=QTimer(self);self._timer.setInterval(16);self._timer.timeout.connect(self._render_next)
        for path in paths:self._add_file(path)
        if not self.list.count():
            self.stop();raise ValueError('No readable PDF pages or images were selected')

    def _add_file(self,path,at=None):
        if engine.EXT_CATEGORY.get(engine.ext_of(path)) not in ('pdf','image'):return 0
        document=None
        try:
            if Path(path).suffix.lower()=='.pdf':
                import pymupdf
                document=pymupdf.open(str(path))
                if document.needs_pass:raise ValueError('Unlock this PDF before arranging its pages')
                count=document.page_count
            else:
                with engine.open_image(path) as image:
                    if image.width<1 or image.height<1:raise ValueError('The picture is empty')
                count=1
        except Exception as error:
            if document is not None:document.close()
            self.error.setText(f'{Path(path).name}: {error}');return 0
        source=len(self.sources);self.sources.append(str(path));self.docs[source]=document
        index=self.list.count() if at is None else max(0,min(at,self.list.count()))
        for page in range(count):
            item=QListWidgetItem();item.setData(Qt.UserRole,[source,page,0]);item.setSizeHint(QSize(140,160))
            item.setTextAlignment(Qt.AlignHCenter|Qt.AlignBottom);self.list.insertItem(index+page,item)
        self._labels();self._timer.start();return count

    def _labels(self):
        for row in range(self.list.count()):
            item=self.list.item(row);source,page,rotation=item.data(Qt.UserRole)
            label=str(row+1)
            if len(self.sources)>1:label+=' · '+Path(self.sources[source]).stem[:14]
            item.setText(label);item.setToolTip(f'{self.sources[source]} · {page+1}')
        self.count.setText(tr('{n} pages',n=self.list.count()))

    def _render_next(self):
        for row in range(self.list.count()):
            item=self.list.item(row);source,page,rotation=item.data(Qt.UserRole);key=(source,page)
            if key in self._thumbnails:continue
            try:
                document=self.docs[source]
                if document is None:
                    with engine.open_image(self.sources[source]) as image:
                        image.thumbnail((256,256));thumbnail=pil_to_qimage(image)
                else:
                    import pymupdf
                    pdf_page=document[page];scale=256/max(pdf_page.rect.width,pdf_page.rect.height)
                    pixmap=pdf_page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),alpha=True)
                    thumbnail=QImage(pixmap.samples,pixmap.width,pixmap.height,pixmap.stride,QImage.Format_RGBA8888).copy()
                self._thumbnails[key]=thumbnail
            except Exception as error:
                self.error.setText(str(error));self._thumbnails[key]=QImage()
            self._icons_for(key);return
        self._timer.stop()

    def _icons_for(self,key):
        image=self._thumbnails.get(key)
        if image is None:return
        for row in range(self.list.count()):
            item=self.list.item(row);source,page,rotation=item.data(Qt.UserRole)
            if (source,page)==key:
                turned=image.transformed(QTransform().rotate(rotation),Qt.SmoothTransformation)
                item.setIcon(QIcon(QPixmap.fromImage(turned)))

    def move_pages(self,rows,destination):
        rows=sorted(set(row for row in rows if 0<=row<self.list.count()))
        insertion=max(0,min(destination,self.list.count()))-sum(row<destination for row in rows)
        selected=[]
        for row in reversed(rows):selected.insert(0,self.list.takeItem(row))
        for offset,item in enumerate(selected):self.list.insertItem(insertion+offset,item);item.setSelected(True)
        self._labels()

    def _turn(self,degrees):
        for item in self.list.selectedItems():
            source,page,rotation=item.data(Qt.UserRole);item.setData(Qt.UserRole,[source,page,(rotation+degrees)%360])
            self._icons_for((source,page))

    def _delete(self):
        selection=self.list.selectedItems()
        if len(selection)==self.list.count():return
        for item in selection:self.list.takeItem(self.list.row(item))
        self._labels()

    def _add_dialog(self):
        paths,_=QFileDialog.getOpenFileNames(self,tr('Add files…'),str(Path(self.sources[0]).parent),
            'PDF / Images (*.pdf *.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff *.heic *.avif *.svg)')
        for path in paths:self._add_file(path)

    def value(self):
        return json.dumps(dict(sources=self.sources,pages=[self.list.item(row).data(Qt.UserRole) for row in range(self.list.count())]))

    def stop(self):
        self._timer.stop()
        for document in self.docs.values():
            if document is not None and not document.is_closed:document.close()
        self.docs.clear();self._stopped=True
