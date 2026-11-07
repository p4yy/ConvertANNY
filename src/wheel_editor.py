"""Per-category orbit visibility and ordering with the actual orbit renderer."""
from copy import deepcopy
import json
from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QComboBox,QListWidget,
    QListWidgetItem,QAbstractItemView,QLabel,QDialogButtonBox)
import engine,design
from i18n import tr


class OrbitPreview(QLabel):
    def __init__(self,parent):
        super().__init__(parent)
        from orbit import OrbitWheel
        import runtime
        self.wheel=OrbitWheel(runtime._APP)
        self.setMinimumSize(320,360);self.setAlignment(Qt.AlignCenter)
        self._configured=False

    def configure(self,mode,paths,operations,selected):
        self.wheel.mode=mode;self.wheel.paths=paths;self.wheel.ops=list(operations)
        self.wheel.hover=selected;self.wheel.page=max(0,selected)//self.wheel.PAGE_SIZE
        self.wheel._t=1.;self._configured=True;self._render()

    def _render(self):
        if not self._configured:return
        image=self.wheel.grab()
        pixels=self.size()*self.devicePixelRatioF()
        image=image.scaled(pixels,Qt.KeepAspectRatio,Qt.SmoothTransformation)
        image.setDevicePixelRatio(self.devicePixelRatioF());self.setPixmap(image)

    def resizeEvent(self,event):
        super().resizeEvent(event);self._render()


class WheelLayoutDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent)
        import runtime
        self.rt=runtime;self.layouts=deepcopy(runtime.wheel_layout());self._key=None
        self._baseline=None;self._global_changed=False;self._ops_now=[]
        self.setWindowTitle('ConvertANNY · '+tr('Wheel slices'));self.setWindowIcon(runtime.app_icon())
        self.setStyleSheet(design.css());self.resize(860,620)
        root=QVBoxLayout(self);root.setContentsMargins(24,24,24,24);root.setSpacing(14)
        selectors=QHBoxLayout();self.mode=QComboBox();self.kind=QComboBox()
        for value,label in runtime.WHEEL_MODES:self.mode.addItem(tr(label),value)
        for value,label in runtime.WHEEL_TYPES:self.kind.addItem(tr(label),value)
        selectors.addWidget(QLabel(tr('Wheel')));selectors.addWidget(self.mode,1)
        selectors.addWidget(QLabel(tr('For')));selectors.addWidget(self.kind,1);root.addLayout(selectors)
        body=QHBoxLayout();self.list=QListWidget()
        self.list.setDragDropMode(QAbstractItemView.InternalMove);self.list.setDefaultDropAction(Qt.MoveAction)
        body.addWidget(self.list,1);self.preview=OrbitPreview(self);body.addWidget(self.preview,1);root.addLayout(body,1)
        hint=QLabel(tr('Untick a slice to hide it. Drag to change the order — the first ones go at the top of the wheel.'))
        hint.setWordWrap(True);hint.setObjectName('dim');root.addWidget(hint)
        self._redraw=QTimer(self);self._redraw.setSingleShot(True);self._redraw.timeout.connect(self._update_preview)
        self.list.itemChanged.connect(lambda *_:self._redraw.start(0))
        self.list.currentRowChanged.connect(lambda *_:self._redraw.start(0))
        self.list.model().rowsMoved.connect(lambda *_:self._redraw.start(0))
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel|QDialogButtonBox.Reset)
        buttons.accepted.connect(self._save_and_close);buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Reset).setText(tr('Reset this wheel'))
        buttons.button(QDialogButtonBox.Reset).clicked.connect(self._reset);root.addWidget(buttons)
        self.mode.currentIndexChanged.connect(self._mode_changed);self.kind.currentIndexChanged.connect(self._load)
        self._mode_changed()
        self.finished.connect(lambda _:self.preview.wheel.deleteLater())

    def _mode_changed(self):
        self.kind.blockSignals(True)
        global_option=self.kind.itemData(0)=='*'
        if self.mode.currentData()=='action' and not global_option:
            self.kind.insertItem(0,tr('All file types'),'*');self.kind.setCurrentIndex(0)
        elif self.mode.currentData()!='action' and global_option:
            self.kind.removeItem(0);self.kind.setCurrentIndex(0)
        self.kind.blockSignals(False);self._load()

    def _paths(self):
        category=self.kind.currentData()
        return ['C:/example/folder'] if category=='folder' else [engine._fake_path('image' if category=='*' else category)]

    def _ops(self,mode,category):
        paths=self._paths()
        if mode=='convert':
            operations=list(engine.conversions(paths))
            # A second source includes the format omitted for same-format inputs.
            source=paths[0].rsplit('.',1)[-1].lower()
            alternate=next((extension for extension,kind in engine.EXT_CATEGORY.items()
                            if kind==category and extension!=source),None)
            if alternate:operations+=engine.conversions([engine._fake_path(category,alternate)])
        elif mode=='tool':operations=list(engine.tools(paths))
        else:operations=list(self.rt._APP.actions.ops(paths)) if self.rt._APP is not None else []
        if self.rt._APP is not None:
            operations.extend(op for op in self.rt.custom_ops_for(mode,paths) if not op.id.startswith('mine:'))
        unique={}
        for operation in operations:unique.setdefault(operation.id,operation)
        return list(unique.values())

    def _snapshot(self):
        order=[];hidden=[]
        for index in range(self.list.count()):
            item=self.list.item(index);key=item.data(Qt.UserRole);order.append(key)
            if item.checkState()!=Qt.Checked:hidden.append(key)
        return dict(order=order,hidden=hidden)

    def _store(self):
        if self._key is None:return
        current=self._snapshot()
        if current==self._baseline:return
        self.layouts[self._key]=current
        if self._key=='action/*':self._global_changed=True

    def _load(self):
        self._store();mode=self.mode.currentData();category=self.kind.currentData();self._key=f'{mode}/{category}'
        config=self.layouts.get(self._key,self.layouts.get('action/*',{}) if mode=='action' else {})
        ranks={key:index for index,key in enumerate(config.get('order',[]))};hidden=set(config.get('hidden',[]))
        self._ops_now=sorted(self._ops(mode,category),key=lambda op:ranks.get(op.id,len(ranks)))
        self.list.blockSignals(True);self.list.clear()
        for operation in self._ops_now:
            item=QListWidgetItem(tr(operation.label));item.setToolTip(tr(operation.hint or ''))
            item.setData(Qt.UserRole,operation.id);item.setFlags(item.flags()|Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked if operation.id in hidden else Qt.Checked);self.list.addItem(item)
        self.list.blockSignals(False);self._baseline=self._snapshot();self._redraw.start(0)

    def _update_preview(self):
        by_id={op.id:op for op in self._ops_now};visible=[];selection=-1
        for index in range(self.list.count()):
            item=self.list.item(index)
            if item.checkState()!=Qt.Checked:continue
            if index==self.list.currentRow():selection=len(visible)
            visible.append(by_id[item.data(Qt.UserRole)])
        self.preview.configure(self.mode.currentData(),self._paths(),visible,selection)

    def _reset(self):
        key=self._key
        if key in self.rt.DEFAULT_WHEEL_LAYOUT:self.layouts[key]=deepcopy(self.rt.DEFAULT_WHEEL_LAYOUT[key])
        else:self.layouts.pop(key,None)
        self._key=None;self._load()

    def _save_and_close(self):
        self._store()
        if self._global_changed:
            self.layouts={key:value for key,value in self.layouts.items() if not key.startswith('action/') or key=='action/*'}
        self.rt.settings().setValue('wheel_layout',json.dumps(self.layouts));self.accept()
