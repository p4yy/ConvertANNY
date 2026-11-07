"""Editors for ConvertANNY conversion profiles and external application actions."""
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog,QFormLayout,QLineEdit,QComboBox,QSpinBox,
    QCheckBox,QDialogButtonBox,QHBoxLayout,QPushButton,QFileDialog)
import design
from i18n import tr


def _shell(dialog,title):
    import runtime
    dialog.setWindowTitle('ConvertANNY · '+tr(title))
    dialog.setWindowIcon(runtime.app_icon())
    dialog.setStyleSheet(design.css())
    dialog.setMinimumWidth(440)
    form=QFormLayout(dialog)
    form.setContentsMargins(24,24,24,24)
    form.setSpacing(14)
    return form


def _buttons(dialog,form,save):
    buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
    buttons.accepted.connect(save);buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)


class PresetDialog(QDialog):
    def __init__(self,kind,spec=None,parent=None):
        super().__init__(parent)
        import engine
        if kind not in ('image','video'):
            raise ValueError('Unsupported preset category')
        self.kind=kind;self._original=deepcopy(spec or {})
        form=_shell(self,'Image preset' if kind=='image' else 'Video preset')
        self.name=QLineEdit(self._original.get('name',''));form.addRow(tr('Name'),self.name)
        self.fmt=QComboBox()
        formats=engine.PRESET_IMAGE_FORMATS if kind=='image' else engine.PRESET_VIDEO_FORMATS
        for value in formats:self.fmt.addItem(value.upper(),value)
        self.fmt.setCurrentIndex(max(0,self.fmt.findData(self._original.get('format'))))
        form.addRow(tr('Format'),self.fmt)
        self.q=QSpinBox();self.q.setRange(10,100);self.q.setSuffix(' %')
        self.q.setValue(int(self._original.get('quality',80 if kind=='image' else 70)))
        form.addRow(tr('Quality'),self.q)
        if kind=='image':
            self.size=QSpinBox();self.size.setRange(0,20000);self.size.setSingleStep(100)
            self.size.setSpecialValueText(tr('Keep the size'));self.size.setSuffix(' px')
            self.size.setValue(int(self._original.get('max_side',1920)))
            form.addRow(tr('Longest side at most'),self.size)
            self.strip=QCheckBox(tr('Remove photo details (location, camera…)'))
            self.strip.setChecked(bool(self._original.get('strip',True)));form.addRow(self.strip)
        else:
            self.height=QComboBox()
            for value in engine.PRESET_VIDEO_HEIGHTS:
                self.height.addItem(tr('Keep the size') if value==0 else f'{value}p',value)
            self.height.setCurrentIndex(max(0,self.height.findData(int(self._original.get('max_height',1080)))))
            form.addRow(tr('Picture size at most'),self.height)
            self.mute=QCheckBox(tr('Remove the sound'));self.mute.setChecked(bool(self._original.get('mute',False)))
            form.addRow(self.mute)
        _buttons(self,form,self.accept)

    def spec(self):
        result=deepcopy(self._original)
        result.update(uid=result.get('uid') or uuid4().hex[:8],kind=self.kind,
                      **{'for':self.kind},name=self.name.text().strip() or tr('Preset'),
                      format=self.fmt.currentData(),quality=self.q.value())
        details=[result['format'].upper()]
        if self.kind=='image':
            result.update(max_side=self.size.value(),strip=self.strip.isChecked())
            details.append(str(result['quality']))
            if result['max_side']:details.append(f"≤{result['max_side']}px")
        else:
            result.update(max_height=self.height.currentData(),mute=self.mute.isChecked())
            if result['max_height']:details.append(f"{result['max_height']}p")
        result['hint']=' · '.join(details)
        return result


class CustomSliceDialog(QDialog):
    def __init__(self,spec=None,parent=None):
        super().__init__(parent)
        import runtime
        self._original=deepcopy(spec or {});self.spec=None
        form=_shell(self,'Custom Slices')
        self.name=QLineEdit(self._original.get('name',''));form.addRow(tr('Name'),self.name)
        parsed=runtime.slice_app(self._original) if self._original else None
        self._raw=None if parsed else self._original.get('command')
        self.app_edit=QLineEdit(parsed[0] if parsed else self._raw or '')
        browse=QPushButton(tr('Browse…'));browse.clicked.connect(self._browse)
        row=QHBoxLayout();row.addWidget(self.app_edit,1);row.addWidget(browse);form.addRow(tr('App'),row)
        self.kind=QComboBox();self.kind.addItem(tr('All files'),['*'])
        for key,label in runtime.WHEEL_TYPES:self.kind.addItem(tr(label),[key])
        selection=self._original.get('for') or ['*']
        if isinstance(selection,str):selection=[selection]
        index=self.kind.findData(selection)
        if index<0:self.kind.addItem(', '.join(selection),selection);index=self.kind.count()-1
        self.kind.setCurrentIndex(index);form.addRow(tr('Show for'),self.kind)
        self.each=QCheckBox(tr('Open each file in its own window'))
        self.each.setChecked(parsed[1] if parsed else bool(self._original.get('each',True)))
        form.addRow(self.each);_buttons(self,form,self._ok)

    def _browse(self):
        import winsys
        selected,_=QFileDialog.getOpenFileName(self,tr('Choose the app…'),self.app_edit.text(),
                                              tr('Apps')+' (*.exe *.bat *.cmd *.lnk);;'+tr('All files')+' (*)')
        if not selected:return
        if selected.lower().endswith('.lnk'):selected=winsys.shortcut_target(selected) or selected
        self._raw=None;self.app_edit.setText(selected)
        if not self.name.text().strip():self.name.setText(tr('Open in {app}',app=Path(selected).stem))

    def _ok(self):
        executable=self.app_edit.text().strip().strip('"')
        if not executable:self.app_edit.setFocus();return
        command=self._raw if self._raw is not None and executable==self._raw.strip().strip('"') else (
            '"'+executable+'" '+('"{file}"' if self.each.isChecked() else '{files}'))
        self.spec=deepcopy(self._original)
        self.spec.update(name=self.name.text().strip() or tr('Open in {app}',app=Path(executable).stem),
                         command=command,each=self.each.isChecked(),**{'for':self.kind.currentData()})
        self.accept()
