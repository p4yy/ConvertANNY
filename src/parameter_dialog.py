"""ConvertANNY tool-parameter form construction and editor lifecycle."""
from pathlib import Path
from PySide6.QtCore import Qt,QPoint
from PySide6.QtGui import QCursor,QGuiApplication
from PySide6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QLabel,QComboBox,QLineEdit,QDialogButtonBox
from i18n import tr


def request_parameters(operation,paths,*,icon,css,factories,on_error):
    dialog=QDialog(None,Qt.WindowStaysOnTopHint)
    title=tr(operation.label).rstrip('…')
    dialog.setWindowTitle('ConvertANNY · '+title);dialog.setWindowIcon(icon);dialog.setStyleSheet(css)
    layout=QVBoxLayout(dialog)
    heading=QLabel(title);heading.setStyleSheet('font-weight:600');layout.addWidget(heading)
    selection=QLabel(Path(paths[0]).name if len(paths)==1 else tr('{n} files',n=len(paths)))
    selection.setTextFormat(Qt.PlainText);selection.setWordWrap(True);selection.setObjectName('dim');layout.addWidget(selection)
    form=QFormLayout();layout.addLayout(form)
    readers={};editors=[];large=False;corners=False
    try:
        for name,default in operation.ask or []:
            if isinstance(default,str) and default in factories:
                try:control=factories[default](paths)
                except Exception as error:
                    on_error('ConvertANNY',str(error));return None
                editors.append(control);readers[name]=control.value;form.addRow(control)
                large=large or default in ('@pages','@sign','@watermark');corners=corners or default=='@corners'
            elif isinstance(default,(list,tuple)):
                control=QComboBox()
                for value in default:control.addItem(tr(str(value)),value)
                form.addRow(tr(name),control);readers[name]=control.currentData
            else:
                control=QLineEdit(str(default or ''))
                if name=='Password':control.setEchoMode(QLineEdit.Password)
                if name in ('Start','End','At time'):
                    control.setPlaceholderText(tr('seconds, m:ss or h:mm:ss'));control.setLayoutDirection(Qt.LeftToRight)
                form.addRow(tr(name),control);readers[name]=control.text
            if name=='Shape' and operation.id=='social':
                shape=control
                preview=factories['social'](paths);preview.set_shape(shape.currentData())
                shape.currentIndexChanged.connect(lambda index,shape=shape,preview=preview:preview.set_shape(shape.currentData()))
                form.addRow(preview);readers['Center']=preview.value;editors.append(preview)
                hint=QLabel(tr('Drag the box to choose what stays in the picture'));hint.setObjectName('dim');form.addRow(hint)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(tr('Apply'));buttons.button(QDialogButtonBox.Cancel).setText(tr('Cancel'))
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        dialog.setMinimumWidth(680 if large else 620 if editors else 340)
        if large:dialog.resize(760,560)
        if large or corners:
            dialog.adjustSize() if corners else None
            screen=QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
            if screen:dialog.move(screen.availableGeometry().center()-QPoint(dialog.width()//2,dialog.height()//2))
        else:dialog.move(QCursor.pos()-QPoint(170,60))
        if dialog.exec()!=QDialog.Accepted:return None
        try:
            return {name:read() for name,read in readers.items()}
        except (ValueError,RuntimeError) as error:
            on_error('ConvertANNY',str(error));return None
    finally:
        for editor in editors:
            stop=getattr(editor,'stop',None)
            if stop:stop()
