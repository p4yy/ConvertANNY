"""Cancellation state and bounded diagnostic capture for desktop tool processes."""
from pathlib import Path
from threading import Event,RLock,Thread
import os
import subprocess
import tempfile


class DesktopCancelToken:
    def __init__(self):
        self._cancel=Event();self._lock=RLock()
        self.procs=[];self.paths=[];self.on_path=None;self.batch=(0,1)

    @property
    def cancelled(self):return self._cancel.is_set()

    def cancel(self):
        self._cancel.set()
        with self._lock:processes=tuple(self.procs)
        for process in processes:
            try:
                if process.poll() is None:process.kill()
            except OSError:pass


def run_tool(command,*,cwd=None,accepted=(0,),duration=0.,span=(0.,1.),detached=False,
             token=None,check=lambda:None,progress=lambda value:None,error_type=RuntimeError,
             on_stderr=None):
    check()
    flags=0
    if os.name=='nt':flags=(0x00000008 if detached else subprocess.CREATE_NO_WINDOW)|0x00004000
    with tempfile.TemporaryFile() as diagnostics:
        process=subprocess.Popen(command,cwd=cwd,stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE if duration>0 else subprocess.DEVNULL,
                                 stderr=subprocess.PIPE if on_stderr else diagnostics,creationflags=flags)
        if token is not None:
            with token._lock:token.procs.append(process)
        reader=None
        error_reader=None
        if on_stderr:
            def diagnostics_reader():
                for raw in process.stderr:
                    diagnostics.write(raw)
                    try:on_stderr(raw.decode('utf-8','replace').rstrip())
                    except Exception:pass
            error_reader=Thread(target=diagnostics_reader,daemon=True);error_reader.start()
        if duration>0:
            def updates():
                last=-1.
                for raw in process.stdout:
                    name,separator,value=raw.partition(b'=')
                    if not separator or name not in (b'out_time_us',b'out_time_ms'):continue
                    try:fraction=max(0.,min(1.,int(value)/(duration*1_000_000)))
                    except ValueError:continue
                    fraction=span[0]+fraction*(span[1]-span[0])
                    if fraction-last>=.005:
                        try:progress(fraction)
                        except Exception:pass
                        last=fraction
            reader=Thread(target=updates,daemon=True);reader.start()
        try:
            while process.poll() is None:
                check()
                try:process.wait(timeout=.1)
                except subprocess.TimeoutExpired:pass
            check()
            if error_reader:error_reader.join(timeout=2)
            if process.returncode not in accepted:
                diagnostics.seek(0,os.SEEK_END);length=diagnostics.tell()
                diagnostics.seek(max(0,length-16384))
                text=diagnostics.read().decode('utf-8','replace').strip()
                raise error_type('\n'.join(text.splitlines()[-4:]) or f'{Path(command[0]).name} failed')
        finally:
            if process.poll() is None:process.kill();process.wait()
            if reader:reader.join(timeout=2)
            if error_reader:error_reader.join(timeout=2)
            if process.stdout:process.stdout.close()
            if process.stderr:process.stderr.close()
            if token is not None:
                with token._lock:
                    if process in token.procs:token.procs.remove(process)
