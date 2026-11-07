import sys,json,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import engine
from PIL import Image
import pymupdf
folder=Path(__file__).parent/'extended';folder.mkdir(exist_ok=True)
results=[]
def test(name,fn):
 try:fn();results.append({'name':name,'passed':True})
 except Exception as e:results.append({'name':name,'passed':False,'error':repr(e)})
def texts():
 for ext,text in [('txt','ConvertANNY test\nText to PDF'),('md','# ConvertANNY\n\nText to **PDF**.'),('html','<h1>ConvertANNY</h1><p>Text to PDF.</p>')]:
  p=folder/('text.'+ext);p.write_text(text,encoding='utf-8');out=engine.text_to_pdf(p,{});doc=pymupdf.open(out);assert 'ConvertANNY' in ''.join(pg.get_text() for pg in doc);doc.close()
test('TXT, Markdown and HTML to searchable PDF',texts)
def pdfs():
 p=folder/'pages.pdf';d=pymupdf.open()
 for i in range(3):pg=d.new_page();pg.insert_text((72,72),'Page '+str(i+1))
 d.save(p);d.close()
 out=engine.pdf_rotate(p,{'Angle':'90'});d=pymupdf.open(out);assert len(d)==3;d.close()
 out=engine.pdf_split(p,{});assert out
test('PDF rotate and split',pdfs)
def subtitles():
 p=folder/'captions.srt';p.write_text('1\n00:00:00,000 --> 00:00:01,000\nHello\n',encoding='utf-8');out=engine.srt_to_vtt(p,{});assert 'WEBVTT' in Path(out).read_text(encoding='utf-8')
test('SRT to VTT',subtitles)
def archives():
 p=folder/'input.txt';p.write_text('archive test');out=engine.pack_paths([p],'7z');assert out.exists()
test('7Z output',archives)
def ai():
 p=folder/'subject.png';Image.new('RGB',(128,128),'white').save(p);out=engine.image_remove_bg(p,{});im=Image.open(out);assert im.mode=='RGBA' and im.size==(128,128)
test('Bundled background removal model inference',ai)
(folder/'report.json').write_text(json.dumps(results,indent=2));print(json.dumps(results,indent=2));sys.exit(0 if all(r['passed'] for r in results) else 1)
