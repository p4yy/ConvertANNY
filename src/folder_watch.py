"""ConvertANNY folder rules, stable-file detection and conversion dispatch."""
from __future__ import annotations
import os
from pathlib import Path
from PySide6.QtCore import QObject,QFileSystemWatcher,QTimer
from PySide6.QtWidgets import (QDialog,QFormLayout,QHBoxLayout,QVBoxLayout,QLineEdit,QPushButton,
 QLabel,QComboBox,QFileDialog,QDialogButtonBox)
import engine
from i18n import tr


def discover_operations(category,path=None,custom_provider=lambda mode,paths:[]):
    examples={'image':['png','jpg'],'video':['mkv','mp4'],'audio':['wav','mp3'],
              'document':['txt','docx'],'subtitle':['vtt','srt']}
    paths=[path] if path else [engine._fake_path(category,extension) for extension in examples.get(category,[''])]
    results=[];seen=set()
    for source in paths:
        selection=[source]
        for mode,catalog in [('convert',engine.conversions(selection)),('tool',engine.tools(selection))]:
            for operation in [*catalog,*custom_provider(mode,selection)]:
                key=(mode,operation.id)
                if key in seen or operation.ui or operation.id=='none':continue
                seen.add(key);results.append((mode,operation))
    return results


class FolderWatch(QObject):
    def __init__(self,app,*,rules,operations,log=lambda message:None):
        super().__init__();self.app=app;self._load=rules;self._operations=operations;self._log=log
        self.fs=QFileSystemWatcher(self);self.fs.directoryChanged.connect(self._scan)
        self.timer=QTimer(self);self.timer.setInterval(1000);self.timer.timeout.connect(self._check)
        self.known={};self.waiting={};self.done=set();self.overwrite=set();self.reload()

    @staticmethod
    def _names(folder):
        try:
            with os.scandir(folder) as entries:return {entry.name for entry in entries if entry.is_file()}
        except OSError:return set()

    def reload(self):
        directories=self.fs.directories()
        if directories:self.fs.removePaths(directories)
        self.rules=[rule for rule in self._load() if isinstance(rule,dict) and rule.get('on',True) and Path(rule.get('folder','')).is_dir() and rule.get('folder')]
        self.known={folder:self._names(folder) for folder in {rule['folder'] for rule in self.rules}}
        self.waiting.clear()
        if self.known:self.fs.addPaths(list(self.known));self.timer.start()
        else:self.timer.stop()

    def _scan(self,folder):
        current=self._names(folder);previous=self.known.get(folder,set());self.known[folder]=current
        for name in current-previous:
            if name.startswith(('.', '~$')) or name.casefold().endswith(('.part','.crdownload','.tmp','.download')):continue
            self.waiting[str(Path(folder)/name)]=(None,0)

    def _check(self):
        for folder in list(self.known):self._scan(folder)
        for filename,(previous,stable) in list(self.waiting.items()):
            path=Path(filename)
            try:
                stat=path.stat();fingerprint=(stat.st_size,stat.st_mtime_ns)
            except OSError:
                self.waiting.pop(filename,None);continue
            stable=stable+1 if fingerprint==previous and stat.st_size>0 else 0
            if stable<2:self.waiting[filename]=(fingerprint,stable);continue
            try:
                with path.open('rb'):pass
            except OSError:
                self.waiting[filename]=(fingerprint,0);continue
            self.waiting.pop(filename,None);self._run(filename)

    def _run(self,filename):
        if filename in self.done:return
        path=Path(filename);category=engine.category_of([filename])
        for rule in self.rules:
            if os.path.normcase(str(path.parent))!=os.path.normcase(rule['folder']) or rule.get('cat') not in ('*',category):continue
            matches=[(mode,operation) for mode,operation in self._operations(category,filename)
                     if operation.id==rule.get('id') and (not rule.get('mode') or mode==rule['mode'])]
            if not matches:continue
            mode,operation=matches[0]
            if operation.model and not engine.model_ready(operation.model):continue
            try:
                destination=path.parent/tr('Converted');destination.mkdir(exist_ok=True)
                parameters={name:value[0] if isinstance(value,(list,tuple)) and value else value for name,value in operation.ask or []}
                if getattr(operation,'spec',None):parameters['_spec']=operation.spec
                self.done.add(filename)
                if rule.get('save')=='overwrite':self.overwrite.add(filename)
                self.app.out_override[filename]=str(destination)
                self._log(f'Auto convert: {operation.id}: {path.name}')
                if operation.group=='action':operation.fn([filename],parameters)
                else:self.app._start(operation,[filename],parameters)
            except Exception as error:
                self.done.discard(filename);self.overwrite.discard(filename);self.app.out_override.pop(filename,None)
                self._log(f'Auto convert failed for {path.name}: {error}')
            return


class WatchRuleDialog(QDialog):
    def __init__(self,parent=None,*,categories,operations,css=''):
        super().__init__(parent);self._operations=operations;self.rule=None
        self.setWindowTitle('ConvertANNY · '+tr('Auto Convert'));self.setStyleSheet(css)
        form=QFormLayout(self);row=QHBoxLayout();self.folder=QLineEdit();self.folder.setMinimumWidth(320)
        choose=QPushButton(tr('Choose…'));choose.clicked.connect(self._pick);row.addWidget(self.folder,1);row.addWidget(choose);form.addRow(tr('Folder'),row)
        self.kind=QComboBox()
        for category,label in categories:
            if category!='folder':self.kind.addItem(tr(label),category)
        self.op=QComboBox();self.save=QComboBox();self.save.addItem(tr('Copy'),'copy');self.save.addItem(tr('Overwrite original'),'overwrite')
        form.addRow(tr('When this arrives'),self.kind);form.addRow(tr('Do this'),self.op);form.addRow(tr('Save result as'),self.save)
        self.note=QLabel();self.note.setWordWrap(True);self.note.setObjectName('dim');form.addRow(self.note)
        self.error=QLabel();self.error.setWordWrap(True);form.addRow(self.error)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.button(QDialogButtonBox.Ok).setText(tr('Save'))
        buttons.accepted.connect(self._ok);buttons.rejected.connect(self.reject);form.addRow(buttons)
        self.kind.currentIndexChanged.connect(self._fill);self.save.currentIndexChanged.connect(self._note);self._fill();self._note()

    def _note(self):
        text='Results go to a “Converted” folder inside it. Files already there are left alone.' if self.save.currentData()=='copy' else "The new file takes the original's place; the original goes to the Recycle Bin. Files already there are left alone."
        self.note.setText(tr(text))
    def _pick(self):
        selected=QFileDialog.getExistingDirectory(self,tr('Pick a folder'),self.folder.text() or str(Path.home()))
        if selected:self.folder.setText(str(Path(selected)))
    def _fill(self):
        self.op.clear()
        for mode,operation in self._operations(self.kind.currentData()):
            label=tr('Convert to {fmt}',fmt=tr(operation.label)) if mode=='convert' and not operation.id.startswith('custom:') else tr(operation.label)
            self.op.addItem(label.rstrip('…'),(mode,operation.id))
    def _ok(self):
        folder=self.folder.text().strip()
        if not folder or not Path(folder).is_dir() or self.op.currentData() is None:
            self.error.setText(tr('Choose a folder and an operation'));return
        mode,identifier=self.op.currentData()
        self.rule=dict(folder=str(Path(folder)),cat=self.kind.currentData(),mode=mode,id=identifier,label=self.op.currentText(),on=True,save=self.save.currentData())
        self.accept()
