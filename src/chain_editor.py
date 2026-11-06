"""Build sequential conversion plans using the operation registry."""
from copy import deepcopy
from uuid import uuid4
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QFormLayout,QHBoxLayout,
    QLineEdit,QComboBox,QListWidget,QWidget,QPushButton,QDialogButtonBox,QMessageBox)
import engine,design
from i18n import tr


class ChainDialog(QDialog):
    def __init__(self,spec=None,parent=None):
        super().__init__(parent)
        import runtime
        self._original=deepcopy(spec or {});self.steps=deepcopy(self._original.get('steps') or [])
        self.setWindowTitle('ConvertANNY · '+tr('Chain'));self.setWindowIcon(runtime.app_icon())
        self.setStyleSheet(design.css());self.resize(560,580)
        root=QVBoxLayout(self);root.setContentsMargins(24,24,24,24);root.setSpacing(14)
        form=QFormLayout();self.name=QLineEdit(self._original.get('name',''));form.addRow(tr('Name'),self.name)
        self.kind=QComboBox()
        for key,label in runtime.WHEEL_TYPES:
            if key not in ('folder','other'):self.kind.addItem(tr(label),key)
        self.kind.setCurrentIndex(max(0,self.kind.findData(self._original.get('for','image'))))
        form.addRow(tr('For'),self.kind);root.addLayout(form)
        self.steps_view=QListWidget();self.steps_view.setAccessibleName(tr('Steps'));root.addWidget(self.steps_view,1)
        row=QHBoxLayout();self.next_op=QComboBox();row.addWidget(self.next_op,1)
        add=QPushButton(tr('Add step'));add.clicked.connect(self._add);row.addWidget(add);root.addLayout(row)
        self.params_box=QWidget();self.params_lay=QFormLayout(self.params_box)
        self.params_lay.setContentsMargins(0,0,0,0);root.addWidget(self.params_box)
        remove=QPushButton(tr('Remove last step'));remove.clicked.connect(self._remove_last);root.addWidget(remove)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._ok);buttons.rejected.connect(self.reject);root.addWidget(buttons)
        self.kind.currentIndexChanged.connect(self._change_kind)
        self.next_op.currentIndexChanged.connect(self._show_params);self._refresh()

    def _change_kind(self):
        self.steps.clear();self._refresh()

    def _ext_now(self):
        extension=engine._fake_path(self.kind.currentData()).rsplit('.',1)[-1]
        for step in self.steps:
            operation=next((item for item in engine.chain_step_ops(extension)
                            if (item.group,item.id)==(step['group'],step['id'])),None)
            if operation:extension=engine._step_ext(extension,operation)
        return extension

    def _refresh(self):
        self.steps_view.clear()
        for number,step in enumerate(self.steps,1):
            settings=', '.join(f'{tr(key)}: {value}' for key,value in step.get('params',{}).items())
            self.steps_view.addItem(f"{number}. {tr(step['label'])}"+(f' ({settings})' if settings else ''))
        self.ops_now=engine.chain_step_ops(self._ext_now())
        self.next_op.blockSignals(True);self.next_op.clear()
        for operation in self.ops_now:
            label=tr('Convert to {fmt}',fmt=tr(operation.label)) if operation.group=='convert' else tr(operation.label)
            self.next_op.addItem(label,(operation.group,operation.id))
        self.next_op.blockSignals(False);self._show_params()

    def _current(self):
        key=self.next_op.currentData()
        return next((operation for operation in self.ops_now if (operation.group,operation.id)==key),None)

    def _show_params(self):
        while self.params_lay.rowCount():self.params_lay.removeRow(0)
        self.param_edits={};operation=self._current()
        if operation is None:return
        for key,default in operation.ask:
            if isinstance(default,(tuple,list)):
                field=QComboBox()
                for value in default:field.addItem(tr(value),value)
            else:
                field=QLineEdit(str(default))
                if key=='Password':field.setEchoMode(QLineEdit.Password)
            self.params_lay.addRow(tr(key),field);self.param_edits[key]=field

    def _add(self):
        operation=self._current()
        if operation is None:return
        values={key:field.currentData() if isinstance(field,QComboBox) else field.text()
                for key,field in self.param_edits.items()}
        self.steps.append(dict(group=operation.group,id=operation.id,params=values,
                               label=f'Convert to {operation.label}' if operation.group=='convert' else operation.label))
        self._refresh()

    def _remove_last(self):
        if self.steps:self.steps.pop();self._refresh()

    def _ok(self):
        if len(self.steps)<2:
            QMessageBox.information(self,'ConvertANNY',tr('A chain needs at least two steps.'));return
        self.accept()

    def spec(self):
        result=deepcopy(self._original)
        result.update(uid=result.get('uid') or uuid4().hex[:8],kind='chain',
                      name=self.name.text().strip() or tr('Chain'),steps=deepcopy(self.steps),
                      hint=' → '.join(tr(step['label']).replace('…','') for step in self.steps)[:60],
                      **{'for':self.kind.currentData()})
        return result
