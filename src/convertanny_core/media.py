"""ConvertANNY-owned media conversion orchestration over the FFmpeg codec backend."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .model import CancelToken, ConversionError
from .paths import OutputPolicy, atomic_write


AUDIO_OUTPUTS = {
    "m4r": ("aac", "-b:a", "192k", "ipod"),
    "mp3": ("libmp3lame", "-q:a", "2", "mp3"),
    "m4a": ("aac", "-b:a", "192k", "ipod"),
    "wav": ("pcm_s16le", "-ar", "44100", "wav"),
    "flac": ("flac", "-compression_level", "5", "flac"),
    "ogg": ("libvorbis", "-q:a", "5", "ogg"),
    "opus": ("libopus", "-b:a", "128k", "opus"),
    "aiff": ("pcm_s16be", "-ar", "44100", "aiff"),
    "wma": ("wmav2", "-b:a", "192k", "asf"),
    "ac3": ("ac3", "-b:a", "448k", "ac3"),
}


def convert_audio(source: str | Path, target_format: str, *, ffmpeg: str,
                  policy: OutputPolicy | None = None,
                  token: CancelToken | None = None) -> Path:
    """Convert the first audio stream and publish only a complete output file."""
    source = Path(source)
    target_format = target_format.lower().lstrip(".")
    try:
        codec, option, value, muxer = AUDIO_OUTPUTS[target_format]
    except KeyError as exc:
        raise ConversionError(f"Unsupported audio output: {target_format}") from exc
    if not source.is_file():
        raise ConversionError(f"File not found: {source}")
    destination = (policy or OutputPolicy()).destination(source, target_format)

    def write(temp: Path):
        command = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                   "-map", "0:a:0", "-vn", "-c:a", codec, option, value, "-f", muxer, str(temp)]
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.PIPE, creationflags=0x08000000 if __import__("os").name == "nt" else 0)
        try:
            while process.poll() is None:
                if token:
                    try:
                        token.check()
                    except Exception:
                        process.kill()
                        process.wait()
                        raise
                try:
                    process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    continue
            error = process.stderr.read().decode("utf-8", "replace").strip() if process.stderr else ""
            if process.returncode:
                if "matches no streams" in error or "does not contain any stream" in error:
                    raise ConversionError("This file has no audio track")
                raise ConversionError(error.splitlines()[-1] if error else "Audio conversion failed")
            if token:
                token.report(1.0)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            if process.stderr:
                process.stderr.close()

    return atomic_write(destination, write, token)


def process_audio(source: str | Path, target_format: str, arguments: list[str], *, ffmpeg: str,
                  suffix: str, policy: OutputPolicy | None = None,
                  before_input: list[str] | None = None,
                  token: CancelToken | None = None) -> Path:
    """Apply an audio filter or trim while retaining the selected output codec."""
    source = Path(source)
    target_format = target_format.lower().lstrip(".")
    try:
        _, _, _, muxer = AUDIO_OUTPUTS[target_format]
    except KeyError as exc:
        raise ConversionError(f"Unsupported audio output: {target_format}") from exc
    codec = AUDIO_OUTPUTS[target_format][0]
    destination = (policy or OutputPolicy(suffix=suffix)).destination(source, target_format)
    def write(temp: Path):
        command = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                   *(before_input or []), "-i", str(source), "-vn", *arguments,
                   "-c:a", codec, "-f", muxer, str(temp)]
        creationflags = 0x08000000 if __import__("os").name == "nt" else 0
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.PIPE, creationflags=creationflags)
        try:
            while process.poll() is None:
                if token:
                    try:
                        token.check()
                    except Exception:
                        process.kill()
                        process.wait()
                        raise
                try:
                    process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    pass
            error = process.stderr.read().decode("utf-8", "replace").strip() if process.stderr else ""
            if process.returncode:
                raise ConversionError(error.splitlines()[-1] if error else "Audio operation failed")
            if token:
                token.report(1.0)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            if process.stderr:
                process.stderr.close()
    return atomic_write(destination, write, token)


def waveform_peaks(source,*,ffmpeg,bins=1200,token=None):
    """Decode to a private scratch stream and reduce it without retaining whole audio in RAM."""
    import tempfile,time
    import numpy as np
    bins=max(1,min(10000,int(bins)));rate=4000
    with tempfile.TemporaryFile() as decoded,tempfile.TemporaryFile() as errors:
        process=subprocess.Popen([ffmpeg,'-nostdin','-hide_banner','-loglevel','error','-i',str(source),
            '-vn','-ac','1','-ar',str(rate),'-f','s16le','pipe:1'],stdout=decoded,stderr=errors,stdin=subprocess.DEVNULL,
            creationflags=0x08000000 if __import__('os').name=='nt' else 0)
        deadline=time.monotonic()+180
        try:
            while process.poll() is None:
                if token:token.check()
                if time.monotonic()>deadline:raise ConversionError('Waveform decoding timed out')
                try:process.wait(timeout=.1)
                except subprocess.TimeoutExpired:pass
            if process.returncode:
                errors.seek(0);raise ConversionError(errors.read(4096).decode('utf-8','replace') or 'Could not decode the audio waveform')
            count=decoded.tell()//2
            if not count:raise ConversionError('This file has no readable audio samples')
            decoded.seek(0);peaks=[];position=0
            for index in range(bins):
                end=(index+1)*count//bins;remaining=(end-position)*2;peak=0.
                while remaining:
                    if token:token.check()
                    block=decoded.read(min(131072,remaining));remaining-=len(block)
                    if not block:raise ConversionError('Waveform data ended unexpectedly')
                    peak=max(peak,float(np.abs(np.frombuffer(block,dtype='<i2').astype(np.float32)).max()))
                peaks.append(peak);position=end
            maximum=max(peaks) or 1.
            return [peak/maximum for peak in peaks],count/rate
        finally:
            if process.poll() is None:process.kill();process.wait()


def create_ringtone(source,clip,format,*,ffmpeg,policy=None,token=None):
    from .video import _duration
    duration=_duration(ffmpeg,Path(source))
    try:
        start,end=map(float,str(clip).split('-'))
    except (TypeError,ValueError) as error:raise ConversionError('Choose a valid ringtone time range') from error
    if duration>0:end=min(end,duration)
    start=max(0,start);end=min(end,start+40)
    if end<=start:raise ConversionError('The ringtone selection is empty')
    length=end-start;fade=min(1.5,length/4)
    arguments=['-t',f'{length:.3f}','-af',f'afade=t=in:d={min(.5,fade):.3f},afade=t=out:st={length-fade:.3f}:d={fade:.3f}']
    target='m4r' if str(format).startswith('iPhone') else 'mp3'
    arguments+=['-b:a','192k'] if target=='m4r' else ['-q:a','2']
    return process_audio(source,target,arguments,ffmpeg=ffmpeg,suffix=' ringtone',policy=policy,
        before_input=['-ss',f'{start:.3f}'],token=token)
