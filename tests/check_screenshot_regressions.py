"""Regression cases from the user's conversion issue screenshots."""
import sys
import tempfile
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from PIL import Image
import pymupdf
import engine


class ScreenshotRegressions(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='convertanny-regression-')
        self.folder=Path(self.temporary.name)
    def tearDown(self):
        self.temporary.cleanup()

    def test_animated_inputs_remain_animated_in_avif(self):
        frames=[Image.new('RGB',(48,32),color) for color in ('red','green','blue')]
        try:
            for extension in ('gif','webp'):
                with self.subTest(extension=extension):
                    source=self.folder/f'animation.{extension}'
                    frames[0].save(source,save_all=True,append_images=frames[1:],duration=[80,160,240],loop=2)
                    output=engine.image_to('avif')(source,{})
                    with Image.open(output) as animation:
                        self.assertEqual(animation.n_frames,3)
                        durations=[];colors=[]
                        for index in range(3):
                            animation.seek(index);animation.load()
                            durations.append(animation.info.get('duration'))
                            colors.append(animation.convert('RGB').getpixel((20,20)))
                        self.assertEqual(durations,[80,160,240]);self.assertEqual(len(set(colors)),3)
        finally:
            for frame in frames:frame.close()

    def test_pdf_merge_retains_navigation_and_forms(self):
        sources=[]
        for number in (1,2):
            source=self.folder/f'document{number}.pdf'
            with pymupdf.open() as document:
                for _ in range(2):document.new_page()
                document[0].insert_link(dict(kind=pymupdf.LINK_GOTO,page=1,to=pymupdf.Point(0,0),**{'from':pymupdf.Rect(10,10,80,30)}))
                widget=pymupdf.Widget();widget.field_name=f'field{number}';widget.field_type=pymupdf.PDF_WIDGET_TYPE_TEXT
                widget.rect=pymupdf.Rect(20,50,150,80);widget.field_value='Retained value';document[0].add_widget(widget)
                document.set_toc([[1,f'Chapter {number}',2]]);document.save(source)
            sources.append(source)
        result=engine.pdf_merge(sources,{})
        with pymupdf.open(result) as document:
            self.assertEqual(document.page_count,4)
            self.assertEqual([entry[2] for entry in document.get_toc()],[2,4])
            for first,target in ((0,1),(2,3)):
                self.assertEqual(document[first].get_links()[0]['page'],target)
                self.assertEqual(next(document[first].widgets()).field_value,'Retained value')


if __name__=='__main__':unittest.main()
