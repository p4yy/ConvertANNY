"""ConvertANNY batch rename controls and live destination preview."""
from pathlib import Path
import re
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog,QHBoxLayout,QVBoxLayout,QFormLayout,QComboBox,QLineEdit,
 QCheckBox,QSpinBox,QLabel,QTableWidget,QTableWidgetItem,QHeaderView,QDialogButtonBox)
from convertanny_core.rename import RenameOptions,plan_names,validate_plan,apply_plan
from i18n import tr


class BatchRenameDialog(QDialog):
    def __init__(self,paths,icon=None,css=''):
        super().__init__(None,Qt.WindowStaysOnTopHint)
        self.paths=sorted(map(str,paths),key=lambda path:[int(part) if part.isdigit() else part.casefold() for part in re.split(r'(\d+)',Path(path).name)])
        self.setWindowTitle('ConvertANNY · '+tr('Rename'))
        if icon is not None:self.setWindowIcon(icon)
        self.setStyleSheet(css);self.resize(820,560)
        root=QHBoxLayout(self);side=QVBoxLayout();form=QFormLayout();side.addLayout(form);side.addStretch();root.addLayout(side)
        def choice(items):
            control=QComboBox()
            for label,value in items:control.addItem(tr(label),value)
            return control
        self.name_mode=choice([('Keep the name','keep'),('New name','new')]);form.addRow(tr('Name'),self.name_mode)
        self.new_name=QLineEdit();form.addRow('',self.new_name)
        self.find,self.repl=QLineEdit(),QLineEdit();form.addRow(tr('Find'),self.find);form.addRow(tr('Replace with'),self.repl)
        self.num_on=QCheckBox(tr('Add a number'));self.num_start,self.num_digits=QSpinBox(),QSpinBox()
        self.num_start.setRange(0,99999);self.num_start.setValue(1);self.num_digits.setRange(1,6);self.num_digits.setValue(max(2,len(str(len(paths)))))
        numbers=QHBoxLayout();numbers.addWidget(QLabel(tr('from')));numbers.addWidget(self.num_start);numbers.addWidget(QLabel(tr('digits')));numbers.addWidget(self.num_digits)
        form.addRow(self.num_on,numbers)
        self.date_on=QCheckBox(tr('Add the date'))
        self.date_src=choice([('Date taken (photos) or modified','taken'),('Date modified','modified'),('Today','today')])
        self.date_fmt=choice([('2026-10-24','%Y-%m-%d'),('24-10-2026','%d-%m-%Y'),('20261024','%Y%m%d')])
        dates=QVBoxLayout();dates.addWidget(self.date_src);dates.addWidget(self.date_fmt);form.addRow(self.date_on,dates)
        self.place=choice([('After the name','after'),('Before the name','before')]);form.addRow(tr('Number and date go'),self.place)
        self.digits=choice([('Keep numerals as they are','keep'),('0123 Western','en'),('٠١٢٣ Arabic','ar')]);form.addRow(tr('Numerals'),self.digits)
        self.case=choice([('Keep','keep'),('lowercase','lower'),('UPPERCASE','upper'),('Title Case','title')]);form.addRow(tr('Letters'),self.case)
        preview=QVBoxLayout();root.addLayout(preview,1)
        self.table=QTableWidget(0,2);self.table.setHorizontalHeaderLabels([tr('Now'),tr('After')]);self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().hide();self.table.setEditTriggers(QTableWidget.NoEditTriggers);preview.addWidget(self.table,1)
        self.status=QLabel();self.status.setWordWrap(True);preview.addWidget(self.status)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        self.ok=buttons.button(QDialogButtonBox.Ok);self.ok.setText(tr('Rename'));buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);preview.addWidget(buttons)
        for control in (self.name_mode,self.date_src,self.date_fmt,self.place,self.digits,self.case):control.currentIndexChanged.connect(self._preview)
        for control in (self.new_name,self.find,self.repl):control.textChanged.connect(self._preview)
        for control in (self.num_on,self.date_on):control.toggled.connect(self._preview)
        for control in (self.num_start,self.num_digits):control.valueChanged.connect(self._preview)
        self.new_name.textChanged.connect(lambda text:self.name_mode.setCurrentIndex(1) if text else None)
        self._preview()

    def new_names(self):
        options=RenameOptions(name=self.new_name.text() if self.name_mode.currentData()=='new' else '',
            find=self.find.text(),replacement=self.repl.text(),numbered=self.num_on.isChecked(),start=self.num_start.value(),padding=self.num_digits.value(),
            dated=self.date_on.isChecked(),date_source=self.date_src.currentData(),date_format=self.date_fmt.currentData(),
            before=self.place.currentData()=='before',numerals=self.digits.currentData(),case=self.case.currentData())
        return list(map(str,plan_names(self.paths,options)))

    def _preview(self):
        try:
            targets=self.new_names();self.table.setRowCount(len(targets))
            for row,(source,target) in enumerate(zip(self.paths,targets)):
                self.table.setItem(row,0,QTableWidgetItem(Path(source).name));self.table.setItem(row,1,QTableWidgetItem(Path(target).name))
            validate_plan(self.paths,targets)
            count=sum(source!=target for source,target in zip(self.paths,targets))
            self.status.setText(tr('{n} of {m} files will be renamed',n=count,m=len(targets)));self.ok.setEnabled(count>0)
        except OSError as error:
            self.status.setText(str(error));self.ok.setEnabled(False)

    def apply(self):
        return apply_plan(self.paths,self.new_names())
