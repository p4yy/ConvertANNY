"""Assertions also run inside the frozen executable, without development Python."""
import json, traceback, time
from pathlib import Path
def run(folder):
    folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=True)
    import engine
    from PIL import Image
    import pymupdf
    tests=[]
    def check(name,fn):
        try:fn();tests.append({'name':name,'passed':True})
        except Exception:tests.append({'name':name,'passed':False,'error':traceback.format_exc()})
    def convert(path,fmt):
        op=next(o for o in engine.conversions([str(path)]) if o.id=='to_'+fmt)
        return engine.run_op(op,[str(path)])[0]
    source=folder/'sample.png';Image.new('RGB',(128,96),'teal').save(source)
    def images():
        for fmt in ['jpg','webp','avif','heic','tiff','bmp','gif','ico','pdf']:
            out=convert(source,fmt);assert Path(out).stat().st_size>0
            if fmt!='pdf':Image.open(out).load()
    check('image formats',images)
    def pdf():
        p=folder/'letter.pdf';doc=pymupdf.open();page=doc.new_page();page.insert_text((72,72),'ConvertANNY verification');doc.save(p);doc.close()
        assert 'ConvertANNY' in Path(convert(p,'txt')).read_text(encoding='utf-8')
        assert len(pymupdf.open(convert(source,'pdf')))==1
    check('PDF text and image PDF',pdf)
    def sheets():
        p=folder/'rows.csv';p.write_text('name,value\nalpha,42\n',encoding='utf-8');out=convert(p,'xlsx')
        import openpyxl
        assert openpyxl.load_workbook(out).active.cell(2,2).value in ('42',42)
    check('spreadsheet CSV to XLSX',sheets)
    def pdf_tables():
        from openpyxl import load_workbook
        p=folder/'table.pdf';doc=pymupdf.open();page=doc.new_page()
        xs,ys=[72,220,350],[72,104,136]
        for y in ys:page.draw_line((xs[0],y),(xs[-1],y))
        for x in xs:page.draw_line((x,ys[0]),(x,ys[-1]))
        page.insert_text((82,94),'Item');page.insert_text((230,94),'Count')
        page.insert_text((82,126),'Notebook');page.insert_text((230,126),'12')
        doc.save(p);doc.close()
        out=convert(p,'xlsx');book=load_workbook(out,read_only=True,data_only=True)
        try:
            sheet=book['Page 1 Table 1']
            assert sheet['A1'].value=='Item' and sheet['B1'].value=='Count'
            assert sheet['A2'].value=='Notebook' and str(sheet['B2'].value)=='12'
        finally:book.close()
    check('PDF tables to XLSX',pdf_tables)
    def archives():
        import zipfile
        out=engine.pack_paths([source],'zip')
        with zipfile.ZipFile(out) as z:assert z.testzip() is None and z.namelist()
    check('archive integrity',archives)
    def watermark():
        out=engine.image_watermark(source,{'Text':'ANNY'});assert Image.open(out).size==(128,96)
    check('watermark regression',watermark)
    def worker():
        from convertanny_core.jobs import ConversionJob
        kind,result=ConversionJob('convert','to_webp',[str(source)],{},None).run(lambda:False)
        assert kind=='done',result
        assert Image.open(result[0]).size==(128,96)
    check('isolated conversion worker',worker)
    def audio():
        import wave
        p=folder/'tone.wav'
        with wave.open(str(p),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\0\0'*16000)
        out=convert(p,'mp3');assert engine.media_duration(out)>.8
    check('FFmpeg WAV to MP3',audio)
    report={'tests':tests,'passed':all(t['passed'] for t in tests)}
    (folder/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return 0 if report['passed'] else 1
