from pathlib import Path
import shutil
from PySide6.QtWidgets import QApplication
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtGui import QImage,QPainter
from PySide6.QtCore import Qt
from PIL import Image
root=Path(__file__).resolve().parents[1];dest=root/'src/assets/brand';dest.mkdir(exist_ok=True)
svg='''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 410 410"><defs><linearGradient id="blue" x1="0" y1="0" x2="0.25" y2="1"><stop stop-color="#0874ff"/><stop offset=".42" stop-color="#0065f7"/><stop offset="1" stop-color="#66acff"/></linearGradient><linearGradient id="paper" x2=".6" y2="1"><stop stop-color="#ffffff"/><stop offset="1" stop-color="#d4e6ff"/></linearGradient><linearGradient id="fold" x2="1" y2="1"><stop stop-color="#d8eaff"/><stop offset="1" stop-color="#72a9fb"/></linearGradient></defs><rect x="3" y="3" width="404" height="404" rx="108" fill="url(#blue)" stroke="#68b9ff" stroke-width="3"/><path d="M85 142 Q43 144 48 185 L67 309 Q72 352 116 348 L226 337 Q262 333 260 296 L249 176Z" fill="#e7f3ff" opacity=".48"/><path d="M119 101 Q77 104 81 147 L94 292 Q98 334 140 330 L255 322 Q296 318 291 278 L280 143Z" fill="#f1f7ff" opacity=".63"/><path d="M159 57 H261 L342 138 V260 Q342 307 296 307 H163 Q118 307 118 261 V102 Q118 57 159 57Z" fill="url(#paper)"/><path d="M261 57 V116 Q261 138 285 138 H342Z" fill="url(#fold)"/><g fill="none" stroke="#0575ff" stroke-width="17" stroke-linecap="round" stroke-linejoin="round"><path d="M170 211 Q177 181 211 181 H290 M262 158 L291 181 L262 204"/><path d="M291 222 Q285 250 251 250 H172 M201 226 L171 250 L201 272"/></g></svg>'''
(dest/'ConvertANNY.svg').write_text(svg)
app=QApplication([]);renderer=QSvgRenderer(svg.encode())
for size in [16,20,24,32,40,44,48,64,96,128,150,256,310,512,1024]:
 im=QImage(size*4,size*4,QImage.Format_ARGB32);im.fill(Qt.transparent);p=QPainter(im);renderer.render(p);p.end();im=im.scaled(size,size,Qt.IgnoreAspectRatio,Qt.SmoothTransformation);im.save(str(dest/f'icon-{size}.png'))
# Use the user's approved supplied derivative in the executable until vector fidelity review passes.
shutil.copy2(root/'branding/icons/windows/ConvertANNY.ico',root/'src/assets/convertanny.ico')
shutil.copy2(root/'branding/icons/png/ConvertANNY_512.png',root/'src/assets/convertanny.png')
