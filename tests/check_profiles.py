"""Exercise profile exports and chain lifecycle with real image/video backends."""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from PIL import Image
import engine
from convertanny_core.model import ConversionError,Cancelled
from convertanny_core.profiles import image_profile,video_profile,execute_chain


def check():
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder);source=root/'photo.png'
        metadata=Image.Exif();metadata[315]='Profile test'
        Image.new('RGB',(640,320),'red').save(source,exif=metadata)
        for strip in (True,False):
            output=image_profile(source,dict(format='jpg',max_side=160,strip=strip))
            with Image.open(output) as image:
                assert image.size==(160,80)
                assert bool(image.getexif().get(315))==(not strip)
        frames=[Image.new('RGB',(120,60),color) for color in ('red','green','blue')]
        animation=root/'animation.gif'
        frames[0].save(animation,save_all=True,append_images=frames[1:],duration=[80,160,240],loop=0)
        output=image_profile(animation,dict(format='avif',max_side=60))
        with Image.open(output) as image:assert image.n_frames==3 and image.size==(60,30)
        steps=[dict(group='convert',id='to_webp'),dict(group='convert',id='to_png')]
        result=engine.run_chain([str(source)],{'_spec':{'steps':steps}})
        assert len(result)==1 and result[0].is_file() and source.is_file()
        assert not list(root.glob('*.webp'))
        try:engine.run_chain([str(source)],{'_spec':{'steps':[steps[0],dict(group='convert',id='missing')]}})
        except ConversionError:pass
        else:raise AssertionError('Invalid chain operation accepted')
        assert not list(root.glob('*.webp'))
        cancelled=False
        def progress(value):
            nonlocal cancelled
            cancelled=True
        def check_cancel():
            if cancelled:raise Cancelled('Test cancellation')
        try:
            execute_chain([source],steps,operations=lambda paths,group:engine.conversions(paths),
                          check=check_cancel,progress=progress)
        except Cancelled:pass
        else:raise AssertionError('Cancelled chain continued')
        assert source.is_file() and not list(root.glob('*.webp'))
        ffmpeg=engine.ffmpeg();video=root/'clip.mp4'
        subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-f','lavfi','-i',
                        'color=c=blue:s=160x100:d=0.3','-c:v','libx264','-pix_fmt','yuv420p',str(video)],
                       check=True,creationflags=0x08000000 if sys.platform=='win32' else 0)
        for extension in ('mp4','webm','mkv'):
            output=video_profile(video,dict(format=extension,max_height=60,mute=True),ffmpeg=ffmpeg)
            probe=subprocess.run([ffmpeg,'-hide_banner','-i',str(output)],capture_output=True,text=True,
                                 creationflags=0x08000000 if sys.platform=='win32' else 0)
            assert output.stat().st_size and '96x60' in probe.stderr
            assert 'Audio:' not in probe.stderr
    print('Profiles: image metadata/resize, animation, chain success/failure/cancel cleanup and three video formats passed')


if __name__=='__main__':check()
