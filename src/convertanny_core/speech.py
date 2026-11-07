"""Offline transcription workflow over the bundled whisper.cpp backend."""
import os
import re
import shutil
import tempfile
from pathlib import Path
from .paths import OutputPolicy,atomic_write
from .processes import run_tool
from .model import ConversionError


def transcribe_audio(source,language,*,ffmpeg,recognizer,model,directory=None,
                     token=None,check=lambda:None,progress=lambda value:None):
    source=Path(source);recognizer=Path(recognizer);model=Path(model)
    if not source.is_file():raise ConversionError(f'File not found: {source.name}')
    if not recognizer.is_file():raise ConversionError('Speech recognition is not included in this build')
    if not model.is_file():raise ConversionError('The speech model is not downloaded yet')
    languages={'Arabic':'ar','English':'en','Detect language':'auto','Translate to English':'auto'}
    if language not in languages:raise ConversionError('Unsupported transcription language')
    policy=OutputPolicy(directory=directory);published=[]
    try:
        with tempfile.TemporaryDirectory(prefix='convertanny-speech-') as folder:
            temporary=Path(folder)
            if token is not None and token.on_path:token.on_path('tmp',str(temporary))
            audio=temporary/'speech.wav';base=temporary/'transcript'
            run_tool([ffmpeg,'-nostdin','-hide_banner','-loglevel','error','-y','-i',str(source),
                      '-vn','-ac','1','-ar','16000','-c:a','pcm_s16le',str(audio)],
                     token=token,check=check,error_type=ConversionError)
            progress(.05)
            command=[str(recognizer),'-m',str(model),'-f',str(audio),'-l',languages[language],
                     '-osrt','-otxt','-of',str(base),'-pp','-t',str(max(1,min(8,(os.cpu_count() or 4)-2)))]
            if language=='Translate to English':command.append('-tr')
            def status(line):
                match=re.search(r'progress\s*=\s*(\d+)%',line)
                if match:progress(.05+.94*min(100,int(match[1]))/100)
            run_tool(command,cwd=str(recognizer.parent),token=token,check=check,
                     on_stderr=status,error_type=ConversionError)
            if not base.with_suffix('.srt').is_file():raise ConversionError('Speech recognition produced no subtitles')
            for extension in ('srt','txt'):
                artifact=base.with_suffix('.'+extension)
                if not artifact.exists():continue
                if extension=='txt' and not artifact.read_text(encoding='utf-8-sig').strip():continue
                check()
                output_policy=policy if extension=='srt' else OutputPolicy(directory=directory,suffix=' transcript')
                output=output_policy.destination(source,extension)
                atomic_write(output,lambda destination,item=artifact:shutil.copyfile(item,destination))
                published.append(output)
                if token is not None:
                    token.paths.append(output)
                    if token.on_path:token.on_path('out',str(output))
            check();progress(1.)
            return published
    except BaseException:
        for path in published:path.unlink(missing_ok=True)
        raise
