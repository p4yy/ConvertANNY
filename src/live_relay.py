"""ConvertANNY live-media relay over a loopback-only HTTP endpoint."""
import http.server
import subprocess
import threading
import time
from uuid import uuid4
import engine


class LiveRelay:
    safe_http=False
    def __init__(self,url,headers=None,client=''):
        import runtime
        self.client=client or engine.yt_client(url);self.procs=[];self._lock=threading.Lock();self._closed=False
        self.last_data=time.monotonic();self.total=0;self.forbidden=False
        arguments=[engine.ffmpeg(),'-nostdin','-hide_banner','-loglevel','warning','-fflags','+genpts']
        extra=[]
        for name,value in (headers or {}).items():
            if any(character in str(name)+str(value) for character in '\r\n'):raise ValueError('Invalid stream header')
            if name.lower()=='user-agent':arguments+=['-user_agent',str(value)]
            else:extra.append(f'{name}: {value}\r\n')
        if extra:arguments+=['-headers',''.join(extra)]
        if 'm3u8' in url.lower() or 'hls' in url.lower():
            arguments+=['-live_start_index','-6','-http_persistent','0' if self.safe_http else '1',
                        '-http_multiple','0' if self.safe_http else '1','-reconnect','1',
                        '-reconnect_on_network_error','1','-reconnect_delay_max','4']
        self._command=[*arguments,*runtime.LIVE_INPUT_EXTRA,'-i',url,'-map','0:v:0?','-map','0:a:0?',
                       '-c','copy',*runtime.LIVE_OUTPUT,'pipe:1']
        relay=self;self._path='/'+uuid4().hex+'/live.ts'
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                if self.path!=relay._path or relay._closed:self.send_error(404);return
                relay._serve(self)
        self.server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.daemon_threads=True
        self.url=f'http://127.0.0.1:{self.server.server_address[1]}{self._path}'
        threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.1},daemon=True).start()

    def _errors(self,process):
        refusals=0
        try:
            for raw in iter(process.stderr.readline,b''):
                if b'403' in raw and b'Forbidden' in raw:
                    refusals+=1
                    if refusals>=3:
                        self.forbidden=True;LiveRelay.safe_http=True
                        if self.client:engine.LIVE_BAD_CLIENTS.add(self.client)
                        if process.poll() is None:process.kill()
                        return
        except (OSError,ValueError):pass

    def _serve(self,handler):
        with self._lock:
            if self._closed:return
            try:process=subprocess.Popen(self._command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=engine.NO_WINDOW)
            except OSError:
                handler.send_error(502,'The stream engine could not start');return
            self.procs.append(process)
        try:
            handler.send_response(200);handler.send_header('Content-Type','video/mp2t');handler.send_header('Cache-Control','no-store');handler.end_headers()
            self.last_data=time.monotonic();reader=threading.Thread(target=self._errors,args=(process,),daemon=True);reader.start()
            while not self._closed:
                chunk=process.stdout.read(65536)
                if not chunk:break
                handler.wfile.write(chunk)
                with self._lock:self.total+=len(chunk);self.last_data=time.monotonic()
        except (OSError,ValueError):pass
        finally:
            self._terminate(process)
            with self._lock:
                if process in self.procs:self.procs.remove(process)

    @staticmethod
    def _terminate(process):
        try:
            if process.poll() is None:process.kill()
            process.wait(timeout=2)
        except (OSError,subprocess.TimeoutExpired):pass
        for stream in (process.stdout,process.stderr):
            if stream:
                try:stream.close()
                except OSError:pass

    def close(self):
        with self._lock:
            if self._closed:return
            self._closed=True;processes=list(self.procs)
        for process in processes:self._terminate(process)
        self.server.shutdown();self.server.server_close()
