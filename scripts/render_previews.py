import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from PySide6.QtCore import Qt,QSettings,QPoint
from PySide6.QtGui import QImage,QPainter,QFontDatabase,QFont
from PySide6.QtWidgets import QApplication
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,str(ROOT/'tmp'/'preview-settings'))
import runtime as rt,design,theme
from workspace import Workspace
from preferences import Preferences

class Stub:
    running=[];waiting=[]
    def show_settings(self):pass
    def open_empty_float(self):pass
    def play_link(self):pass
    def read_qr_on_screen(self):pass
    def show_tour(self,*a):pass
    def apply_theme(self):pass
    def apply_language(self):pass
    def _build_tray_menu(self):pass
    def show_help(self):pass

app=QApplication([]);app.setStyle('Fusion');app.setApplicationName('ConvertANNY preview');app.setOrganizationName('ConvertANNY preview')
design.install();theme.set_mode('dark');QFontDatabase.addApplicationFont(rt.asset('fonts/InterVariable.ttf'));app.setFont(QFont('Inter Variable Text',10));app.setPalette(design.palette());app.setStyleSheet(design.css())
out=ROOT/'docs'/'screenshots';out.mkdir(parents=True,exist_ok=True)
def render(widget,name,size):
    widget.resize(*size);widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen,True);widget.ensurePolished()
    for child in [widget,*widget.findChildren(type(widget))] if False else [widget,*widget.findChildren(__import__('PySide6.QtWidgets',fromlist=['QWidget']).QWidget)]:
        child.ensurePolished()
        if child.layout():child.layout().activate()
    app.processEvents()
    image=QImage(size[0],size[1],QImage.Format.Format_ARGB32_Premultiplied);image.fill(0xff101012)
    painter=QPainter(image);widget.render(painter,QPoint(0,0));painter.end();image.save(str(out/name));widget.close()

stub=Stub();home=Workspace(stub);render(home,'workspace-dark.png',(1160,820))
activity=Workspace(stub);activity.page(1);render(activity,'activity-empty.png',(1160,820))
prefs=Preferences(stub);prefs.nav.setCurrentRow(0);render(prefs,'preferences-general.png',(1280,860))
prefs=Preferences(stub);prefs.nav.setCurrentRow(1);render(prefs,'preferences-wheel.png',(1280,860))
print('Rendered app window previews:',', '.join(p.name for p in sorted(out.glob('*.png'))))
