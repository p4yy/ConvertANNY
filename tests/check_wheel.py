import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt,QPointF
from PySide6.QtTest import QTest
from PIL import Image
import engine,design,theme
from orbit import OrbitWheel,_label_layout
from PySide6.QtGui import QFontMetrics
app=QApplication([]);design.install();theme.set_mode('dark')

for available_width in (48,96,120,170):
    fitted,font=_label_layout('Convert the selected animated image to the chosen output format',available_width,76)
    bounds=QFontMetrics(font).boundingRect(0,0,available_width,76,Qt.AlignCenter|Qt.TextWordWrap,fitted)
    assert bounds.height()<=76 and bounds.width()<=available_width
with tempfile.TemporaryDirectory() as temporary:
 folder=Path(temporary);source=folder/'input.png';Image.new('RGB',(64,48),'blue').save(source)
 class Controller:
  result=None
  def ops_for(self,mode,paths):return engine.conversions(paths)
  def execute(self,op,paths):self.result=engine.run_op(op,paths)
 controller=Controller();wheel=OrbitWheel(controller);wheel.popup('convert',[str(source)],click_mode=True)
 QTest.qWait(250)
 QTest.keyClick(wheel,Qt.Key_Down);QTest.keyClick(wheel,Qt.Key_Return);QTest.qWait(300)
 assert controller.result
 with Image.open(controller.result[0]) as result:
  assert result.size==(64,48)
 assert not wheel.is_open()
print('Wheel keyboard selection, real image conversion and dismissal: passed')
