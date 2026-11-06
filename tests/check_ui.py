import os,sys

from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
import runtime as rt,design,theme
from preferences import Preferences
from orbit import OrbitWheel
app=QApplication([]);design.install();theme.set_mode('dark');QFontDatabase.addApplicationFont(rt.asset('fonts/InterVariable.ttf'))
class Stub:
 def check_updates(self,**kw):pass
 def show_tour(self,*a):pass
 def apply_theme(self):pass
 def apply_language(self):pass
 def _build_tray_menu(self):pass
 def show_help(self):pass
s=Stub();p=Preferences(s);p.show();app.processEvents()
assert p.nav.count()==8
for i in range(8):p.nav.setCurrentRow(i);app.processEvents();assert p.stack.currentIndex()==i
assert not rt.app_icon().isNull()
assert 'Inter Variable' in QFontDatabase.families()
assert p.release_repo is not None
print('Preferences pages, approved icon and bundled Inter: passed')
p.close()
