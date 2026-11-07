import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage,QPainter,QPalette
from PySide6.QtCore import Qt
import theme,design
from workspace import Workspace
class Stub:
 running=set();waiting=[]
 def __getattr__(self,name):return lambda *a,**kw:None
app=QApplication([]);design.install();home=Workspace(Stub())
for mode in ['light','dark','light']:
 theme.set_mode(mode);app.setPalette(design.palette());app.setStyleSheet(design.css());home.setStyleSheet(design.css());home.ensurePolished();app.processEvents()
 panel=home.op_area.widget();panel.resize(300,300);panel.ensurePolished()
 image=QImage(300,300,QImage.Format_ARGB32);image.fill(Qt.magenta);panel.render(image)
 pixel=image.pixelColor(290,290);value=pixel.lightness()
 assert (value>220 if mode=='light' else value<50),(mode,pixel.name())
 assert (app.palette().color(QPalette.Base).lightness()>220 if mode=='light' else app.palette().color(QPalette.Base).lightness()<50)
 print(mode,'operation panel:',pixel.name(),'passed')
home.timer.stop()
