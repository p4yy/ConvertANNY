"""Execute saved conversion profiles and sequential operation plans."""
from pathlib import Path
import re
from .images import convert_image
from .video import process_video
from .model import ConversionError
from .paths import OutputPolicy


def _policy(source,profile,directory):
    label=re.sub(r'[\x00-\x1f<>:"/\\|?*]','',str(profile.get('name','preset'))).strip(' .')[:30]
    return OutputPolicy(directory=directory,suffix=' '+label if label else '')


def image_profile(source,profile,*,directory=None,token=None):
    return convert_image(source,str(profile.get('format','webp')),quality=int(profile.get('quality',80)),
                         max_side=int(profile.get('max_side') or 0),strip_metadata=bool(profile.get('strip',True)),
                         strip_icc=bool(profile.get('strip_icc',False)),
                         policy=_policy(source,profile,directory),token=token)


def video_profile(source,profile,*,ffmpeg,directory=None,token=None):
    extension=str(profile.get('format','mp4')).lower()
    if extension not in ('mp4','webm','mkv'):raise ConversionError('Unsupported video preset format')
    quality=max(10,min(100,int(profile.get('quality',70))))
    height=max(0,int(profile.get('max_height') or 0))
    arguments=['-map','0:v:0','-map','0:a:0?','-sn','-dn']
    if height:
        arguments+=['-vf',f"scale=-2:trunc(min({height}\\,ih)/2)*2"]
    else:
        arguments+=['-vf','scale=trunc(iw/2)*2:trunc(ih/2)*2']
    if extension=='webm':
        arguments+=['-c:v','libvpx-vp9','-crf',str(round(50-quality*.3)),'-b:v','0',
                     '-deadline','good','-cpu-used','5','-row-mt','1','-c:a','libopus','-b:a','128k']
    else:
        arguments+=['-c:v','libx264','-preset','medium','-crf',str(round(35-quality*.17)),
                     '-pix_fmt','yuv420p','-c:a','aac','-b:a','160k']
        if extension=='mp4':arguments+=['-movflags','+faststart']
    if profile.get('mute'):arguments+=['-an']
    return process_video(source,extension,arguments,ffmpeg=ffmpeg,suffix='',
                         policy=_policy(source,profile,directory),token=token)


def execute_chain(sources,steps,*,operations,check=lambda:None,progress=lambda value:None):
    """Resolve each step against its current input; retire intermediate files even on failure."""
    if not steps:raise ConversionError('This chain has no steps')
    current=[Path(source) for source in sources]
    originals={path.resolve() for path in current}
    produced=set();final=set()
    def flatten(value):
        if isinstance(value,(list,tuple)):
            for item in value:yield from flatten(item)
        elif value is not None:yield Path(value)
    try:
        for number,step in enumerate(steps):
            check()
            operation=next((op for op in operations([str(path) for path in current],step.get('group'))
                            if op.id==step.get('id')),None)
            if operation is None:raise ConversionError(f'Step {number+1} cannot process these files')
            parameters=dict(step.get('params') or {});outputs=[]
            batches=[current] if operation.multi else [[path] for path in current]
            for batch in batches:
                check()
                value=operation.fn([str(path) for path in batch] if operation.multi else str(batch[0]),parameters)
                for path in flatten(value):
                    if not path.exists():raise ConversionError(f'Step {number+1} did not create {path.name}')
                    outputs.append(path)
                    if path.resolve() not in originals:produced.add(path.resolve())
            if not outputs:raise ConversionError(f'Step {number+1} produced no files')
            current=outputs;progress((number+1)/len(steps))
        check();final={path.resolve() for path in current}
        return current
    finally:
        # Never recursively remove a directory: extractors can return user-owned folders.
        for path in produced-originals-final:
            try:
                if path.is_file():path.unlink()
            except OSError:pass
