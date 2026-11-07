"""File-first workspace, operation browser and persistent activity history."""
import json, math, time
from pathlib import Path
from PySide6.QtCore import Qt, QRectF, QPointF, QTimer, QUrl
from PySide6.QtGui import QPainter, QPen, QFont, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (QWidget,QMainWindow,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
    QFileDialog,QListWidget,QListWidgetItem,QStackedWidget,QLineEdit,QScrollArea,QGridLayout,QFrame,QMessageBox)
import runtime as rt
import theme, design, icons

def label(text, name=''):
    w=QLabel(text); w.setObjectName(name); w.setWordWrap(True); return w

def button(text, callback, name=''):
    w=QPushButton(text); w.setObjectName(name); w.setCursor(Qt.PointingHandCursor); w.clicked.connect(callback); return w

class DropCanvas(QWidget):
    def __init__(self, owner):
        super().__init__(); self.owner=owner; self.setMinimumHeight(220); self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName('Choose files or drop files into the workspace')
    def mouseReleaseEvent(self,e):
        if e.button()==Qt.LeftButton: self.owner.pick()
    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        c=QPointF(self.width()/2,self.height()/2-25)
        p.setPen(QPen(theme.color('border'),1,Qt.DashLine)); p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(1,1,self.width()-2,self.height()-2),18,18)
        p.drawPixmap(int(c.x()-40),int(c.y()-40),rt.app_icon().pixmap(80,80))
        p.setPen(theme.color('text')); p.setFont(QFont('ConvertANNY UI',12,QFont.DemiBold))
        p.drawText(QRectF(10,c.y()+88,self.width()-20,28),Qt.AlignCenter,'Drop files here')
        p.setPen(theme.color('dim')); p.setFont(QFont('ConvertANNY UI',9))
        p.drawText(QRectF(10,c.y()+118,self.width()-20,24),Qt.AlignCenter,'Images, documents, media or whole folders')
        p.end()

class Workspace(QMainWindow):
    def __init__(self,controller):
        super().__init__(); self.controller=controller; self.paths=[]; self.mode='convert'; self.records=[]
        self.setWindowTitle('ConvertANNY'); self.setWindowIcon(rt.app_icon()); self.resize(1160,820); self.setMinimumSize(900,650)
        self.setAcceptDrops(True)
        root=QWidget(); root.setObjectName('workspace'); self.setCentralWidget(root)
        v=QVBoxLayout(root); v.setContentsMargins(36,24,36,20); v.setSpacing(22)
        head=QHBoxLayout()
        mark=QLabel();mark.setPixmap(rt.app_icon().pixmap(32,32));head.addWidget(mark)
        brand=label('ConvertANNY');brand.setStyleSheet('font-size:19px;font-weight:700;');head.addWidget(brand);head.addStretch()
        self.nav=[]
        for title,action in [('Workspace',lambda:self.page(0)),('Activity',lambda:self.page(1)),('Guide',lambda:self.page(2))]:
            b=button(title,action,'nav'); b.setCheckable(True); self.nav.append(b); head.addWidget(b)
        for b,name in zip(self.nav,['workspace','activity','guide']):b.setIcon(icons.icon(name))
        self.preferences_button=button('Preferences',controller.show_settings,'nav');self.preferences_button.setIcon(icons.icon('general'));head.addWidget(self.preferences_button);v.addLayout(head)
        self.stack=QStackedWidget(); v.addWidget(self.stack,1)
        self.stack.addWidget(self.make_work()); self.stack.addWidget(self.make_activity()); self.stack.addWidget(self.make_guide())
        footer=QHBoxLayout(); self.status=label('Ready','muted'); footer.addWidget(self.status); footer.addStretch()
        privacy=label('Local conversions','muted');privacy.setWordWrap(False);footer.addWidget(privacy);v.addLayout(footer)
        self.page(0); self.setStyleSheet(design.css()); self.refresh_activity()
        QShortcut(QKeySequence('Ctrl+O'),self,activated=self.pick)
        QShortcut(QKeySequence('Ctrl+K'),self,activated=self.open_wheel)
        QShortcut(QKeySequence('Delete'),self,activated=self.remove_selected)
        self.timer=QTimer(self,interval=1000,timeout=self.tick); self.timer.start()

    def make_work(self):
        w=QWidget(); v=QVBoxLayout(w); v.setContentsMargins(0,12,0,0); v.setSpacing(12)
        v.addWidget(label('','eyebrow'))
        v.addWidget(label('Convert files','hero'))
        v.addWidget(label('Add files to choose a format or tool.','muted')); v.addSpacing(14)
        row=QHBoxLayout(); row.setSpacing(24)
        left=QFrame(); left.setObjectName('card'); lv=QVBoxLayout(left); lv.setContentsMargins(22,22,22,22); lv.setSpacing(14)
        lh=QHBoxLayout(); self.file_count=label('Files','eyebrow'); lh.addWidget(self.file_count); lh.addStretch(); lh.addWidget(button('Clear',self.clear)); lv.addLayout(lh)
        self.drop=DropCanvas(self); lv.addWidget(self.drop,1)
        self.files=QListWidget(); self.files.setSelectionMode(QListWidget.ExtendedSelection); self.files.itemDoubleClicked.connect(lambda _:self.preview()); self.files.hide(); lv.addWidget(self.files,1)
        buttons=QHBoxLayout(); buttons.addWidget(button('＋  Add files',self.pick,'primary')); buttons.addWidget(button('Add folder',self.pick_folder)); lv.addLayout(buttons)
        tools=QHBoxLayout(); self.preview_button=button('Preview',self.preview); self.preview_button.setEnabled(False); tools.addWidget(self.preview_button)
        self.orbit_button=button('Open orbit  ↗',self.open_wheel); self.orbit_button.setEnabled(False); tools.addWidget(self.orbit_button); lv.addLayout(tools)
        row.addWidget(left,5)
        right=QWidget(); rv=QVBoxLayout(right); rv.setContentsMargins(0,0,0,0); rv.setSpacing(14)
        rv.addWidget(label('Actions','eyebrow'))
        tabs=QHBoxLayout(); self.mode_buttons=[]
        for mode,title in [('convert','Convert'),('tool','Tools'),('action','Actions')]:
            b=button(title,lambda _=False,m=mode:self.set_mode(m),'nav'); b.setCheckable(True); self.mode_buttons.append((mode,b)); tabs.addWidget(b)
        rv.addLayout(tabs)
        self.search=QLineEdit(); self.search.setPlaceholderText('Find a format or action…'); self.search.textChanged.connect(self.refresh_ops); rv.addWidget(self.search)
        self.op_area=QScrollArea(); self.op_area.setWidgetResizable(True); rv.addWidget(self.op_area,1)
        self.output=label('Outputs are saved beside the original.','muted'); rv.addWidget(self.output)
        row.addWidget(right,6); v.addLayout(row,1); self.set_mode('convert'); return w

    def make_activity(self):
        w=QWidget(); v=QVBoxLayout(w); v.setContentsMargins(0,12,0,0)
        v.addWidget(label('','eyebrow')); v.addWidget(label('Activity','hero'))
        self.jobs=QListWidget(); v.addWidget(self.jobs,1)
        row=QHBoxLayout(); row.addWidget(button('Open result',self.open_result)); row.addWidget(button('Show in Explorer',self.reveal_result)); row.addStretch()
        row.addWidget(button('Cancel active jobs',self.cancel_jobs)); v.addLayout(row); return w

    def make_guide(self):
        w=QWidget(); v=QVBoxLayout(w); v.setContentsMargins(0,12,0,0); v.setSpacing(20)
        v.addWidget(label('','eyebrow')); v.addWidget(label('How to use ConvertANNY','hero'))
        for title,text in [('01   Bring a file','Drop files into this workspace, or select files in Explorer and press Ctrl + Alt + Space.'),('02   Choose a direction','While dragging a file, tap Shift for conversions, Ctrl for tools or Alt for file actions. Scroll to choose; release over a segment to run it.'),('03   Keep moving','Jobs run in separate background processes. Follow progress or cancel in Activity. Originals stay intact unless you choose replacement in Preferences.')]:
            v.addWidget(label(title,'pagetitle')); v.addWidget(label(text,'muted'))
        row=QHBoxLayout(); row.addWidget(button('Open floating player',self.controller.open_empty_float)); row.addWidget(button('Play a copied link',self.controller.play_link)); row.addWidget(button('Read QR on screen',lambda:QTimer.singleShot(350,self.controller.read_qr_on_screen))); v.addLayout(row)
        v.addWidget(label('Configure gestures, sounds, folder rules, presets, chains and your own commands in Preferences. Close the workspace to keep the orbit running in the tray.','muted')); v.addStretch(); return w

    def page(self,i):
        self.stack.setCurrentIndex(i)
        for j,b in enumerate(self.nav):
            b.setChecked(i==j);b.setIcon(icons.icon(['workspace','activity','guide'][j],i==j))
        if i==1: self.refresh_activity()

    def pick(self):
        paths,_=QFileDialog.getOpenFileNames(self,'Add files',rt.settings().value('last_dir',''))
        if paths:
            rt.settings().setValue('last_dir',str(Path(paths[0]).parent)); self.add_paths(paths)

    def pick_folder(self):
        p=QFileDialog.getExistingDirectory(self,'Add a folder')
        if p:self.add_paths([p])

    def add_paths(self,paths):
        for p in paths:
            p=str(Path(p).resolve())
            if Path(p).exists() and p not in self.paths:self.paths.append(p)
        self.sync_files(); self.page(0)

    def sync_files(self):
        self.files.clear()
        for p in self.paths:
            item=QListWidgetItem(Path(p).name+'\n'+str(Path(p).parent)); item.setToolTip(p); self.files.addItem(item)
        active=bool(self.paths); self.files.setVisible(active); self.drop.setVisible(not active)
        self.preview_button.setEnabled(active); self.orbit_button.setEnabled(active)
        self.file_count.setText(f'{len(self.paths)} files' if active else 'Files'); self.refresh_ops()

    def clear(self):self.paths=[];self.sync_files()

    def remove_selected(self):
        if self.files.hasFocus():
            remove={self.files.row(i) for i in self.files.selectedItems()}; self.paths=[p for i,p in enumerate(self.paths) if i not in remove];self.sync_files()

    def preview(self):
        if self.paths:
            i=max(0,self.files.currentRow());self.controller._show_peek([self.paths[i]])

    def open_wheel(self):
        if self.paths:self.controller.wheel.popup(self.mode,list(self.paths),click_mode=True,at=self.mapToGlobal(self.rect().center()))
        else:self.pick()

    def set_mode(self,mode):
        self.mode=mode
        for m,b in self.mode_buttons:b.setChecked(m==mode)
        self.refresh_ops()

    def refresh_ops(self,*_):
        container=QWidget();container.setObjectName('operationList');container.setAttribute(Qt.WA_StyledBackground,True)
        grid=QGridLayout(container); grid.setContentsMargins(0,0,8,0); grid.setSpacing(10)
        if not self.paths:
            empty=label('Add files to see compatible operations.','muted'); grid.addWidget(empty,0,0)
        else:
            ops=(rt.engine.conversions(self.paths) if self.mode=='convert' else rt.engine.tools(self.paths) if self.mode=='tool' else self.controller.actions.ops(self.paths))
            ops+=rt.custom_ops_for(self.mode,self.paths)
            query=self.search.text().casefold()
            ops=[o for o in ops if o.id!='none' and query in (o.label+' '+o.hint).casefold()]
            for i,op in enumerate(ops):
                text=rt.tr(op.label)
                if op.hint:text+='\n'+rt.tr(op.hint)
                b=button(text,lambda _=False,o=op:self.controller.execute(o,list(self.paths)),'action')
                b.setMinimumHeight(64); b.setToolTip(rt.tr(op.label)+(('\n'+rt.tr(op.hint)) if op.hint else '')); grid.addWidget(b,i//2,i%2)
            if not ops:grid.addWidget(label('No matching actions. Try another search.','muted'),0,0)
        grid.setRowStretch(grid.rowCount(),1)
        self.op_area.setWidget(container)

    def refresh_activity(self):
        self.jobs.clear()
        for w in list(self.controller.running)+list(self.controller.waiting):
            status='Cancelling' if w.cancel_requested else ('Queued' if w in self.controller.waiting else 'Running')
            self.jobs.addItem(f'{status}  ·  {w.op.label}\n{Path(w.paths[0]).name}')
        try:history=json.loads(rt.settings().value('activity','[]'))
        except (TypeError,ValueError):history=[]
        for entry in history:
            item=QListWidgetItem(f"{entry['status']}  ·  {entry['label']}\n{entry.get('detail','')}")
            item.setData(Qt.UserRole,entry.get('path'));self.jobs.addItem(item)
        if not self.jobs.count():self.jobs.addItem('Nothing here yet. Your completed and failed jobs will appear here.')

    def selected_result(self):
        item=self.jobs.currentItem();p=item.data(Qt.UserRole) if item else None
        return p if p and Path(p).exists() else None
    def open_result(self):
        p=self.selected_result()
        if p:QDesktopServices.openUrl(QUrl.fromLocalFile(p))
    def reveal_result(self):
        p=self.selected_result()
        if p:rt.winsys.reveal(p)
    def cancel_jobs(self):
        for w in list(self.controller.running)+list(self.controller.waiting):self.controller._cancel_job(w)
        self.refresh_activity()
    def tick(self):
        n=len(self.controller.running); q=len(self.controller.waiting)
        self.status.setText(f'{n} running · {q} queued' if n or q else 'Ready')
        mode=rt.settings().value('output_mode','next'); folder=rt.settings().value('output_dir','')
        self.output.setText({'next':'Outputs are saved beside the original.','folder':f'Output folder: {folder}','replace':'Results replace originals (configured in Preferences).','clipboard':'Results are copied to the clipboard.'}.get(mode,'Outputs are saved beside the original.'))
        if self.stack.currentIndex()==1 and (n or q):self.refresh_activity()
    def dragEnterEvent(self,e):
        if e.mimeData().hasUrls():e.acceptProposedAction()
    def dropEvent(self,e):
        self.add_paths([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]); e.setDropAction(Qt.CopyAction);e.accept()
    def closeEvent(self,e):
        self.hide();e.ignore()

class Controller(rt.ConvertANNYApp):
    def __init__(self,qapp):
        super().__init__(qapp);self.home=Workspace(self)
        self.tray.activated.disconnect()
        self.tray.activated.connect(lambda reason:self.show_home() if reason==rt.QSystemTrayIcon.Trigger else None)
        self._menu.insertAction(self._first_action,rt.QAction('Open workspace',self,triggered=self.show_home))
    def show_home(self):self.home.show();self.home.raise_();self.home.activateWindow()
    def show_tour(self,parent=None):self.show_home();self.home.page(2)
    def show_help(self):self.show_home();self.home.page(2)
    def apply_theme(self):
        super().apply_theme();self.qapp.setPalette(design.palette());self.qapp.setStyleSheet(design.css())
        if hasattr(self,'home'):self.home.setStyleSheet(design.css());self.home.drop.update()
        if hasattr(self,'home'):
            self.home.page(self.home.stack.currentIndex());self.home.preferences_button.setIcon(icons.icon('general'))
    def _done(self,worker,outs,err):
        super()._done(worker,outs,err)
        try:history=json.loads(rt.settings().value('activity','[]'))
        except (TypeError,ValueError):history=[]
        status='Cancelled' if err==rt.CANCELLED else ('Failed' if err else ('Partial' if worker.failed else 'Completed'))
        recent=json.loads(rt.settings().value('recent_results','[]'))
        output=recent[0]['path'] if not err and recent else None
        history.insert(0,dict(status=status,label=worker.op.label,detail=str(err or (Path(output).name if output else Path(worker.paths[0]).name)),path=output,time=time.time()))
        rt.settings().setValue('activity',json.dumps(history[:100]));self.home.refresh_activity()
