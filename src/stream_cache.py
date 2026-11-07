"""ConvertANNY bounded download-ahead cache and local HTTP range service."""
from __future__ import annotations
import http.server
import os
import re
import tempfile
import threading
import time
import urllib.request
from urllib.parse import urlparse,parse_qs
from uuid import uuid4


def byte_range(header,size):
    if not header:return 0,size-1,False
    match=re.fullmatch(r'bytes=(\d*)-(\d*)',header.strip())
    if match is None or not any(match.groups()):raise ValueError('Unsupported byte range')
    first,last=match.groups()
    if not first:
        length=int(last)
        if length<=0:raise ValueError('Empty byte range')
        return max(0,size-length),size-1,True
    start=int(first);end=min(size-1,int(last)) if last else size-1
    if start>=size or end<start:raise ValueError('Byte range outside stream')
    return start,end,True


class StreamCache:
    CHUNK=2*1024*1024;WORKERS=4;AHEAD=64*1024*1024
    def __init__(self,url,headers=None,size=None):
        if urlparse(url).scheme not in ('http','https'):raise OSError('Stream requires HTTP or HTTPS')
        self.url=url;self.headers={'User-Agent':'ConvertANNY/0.1',**(headers or {})}
        self.closed=False;self.expired=False;self.fails=0;self.forbidden=0;self.focus=0
        self.cond=threading.Condition();self.flock=threading.Lock();self.busy=set();self._attempts={}
        reported=size or parse_qs(urlparse(url).query).get('clen',[0])[0]
        self.size=int(reported or 0) or self._probe_size()
        if self.size<=0:raise OSError('Stream length is unavailable')
        self.n=(self.size+self.CHUNK-1)//self.CHUNK;self.have=bytearray(self.n)
        descriptor,self.tmp=tempfile.mkstemp(prefix='convertanny-stream-',suffix='.bin');os.close(descriptor)
        self.f=open(self.tmp,'r+b');self.f.truncate(self.size)
        self._path='/'+uuid4().hex+'/media';cache=self
        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version='HTTP/1.1'
            def log_message(self,*args):pass
            def do_HEAD(self):self._serve(False)
            def do_GET(self):self._serve(True)
            def _serve(self,body):
                if self.path!=cache._path:self.send_error(404);return
                try:start,end,partial=byte_range(self.headers.get('Range'),cache.size)
                except ValueError:
                    self.send_response(416);self.send_header('Content-Range',f'bytes */{cache.size}');self.send_header('Content-Length','0');self.end_headers();return
                self.send_response(206 if partial else 200)
                self.send_header('Accept-Ranges','bytes');self.send_header('Content-Type','application/octet-stream')
                self.send_header('Content-Length',str(end-start+1))
                if partial:self.send_header('Content-Range',f'bytes {start}-{end}/{cache.size}')
                self.end_headers()
                if not body:return
                cache.set_focus(start);position=start
                try:
                    while position<=end and not cache.closed:
                        index=position//cache.CHUNK
                        if not cache.wait_chunk(index):self.close_connection=True;return
                        limit=min(end+1,(index+1)*cache.CHUNK)
                        with cache.flock:
                            if cache.closed:return
                            cache.f.seek(position);block=cache.f.read(limit-position)
                        if not block:return
                        self.wfile.write(block);position+=len(block);cache.set_focus(min(position,cache.size-1))
                except (OSError,ValueError):self.close_connection=True
        try:
            self.server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.daemon_threads=True
            self.local=f'http://127.0.0.1:{self.server.server_address[1]}{self._path}'
            threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.1},daemon=True).start()
            self._threads=[threading.Thread(target=self._worker,daemon=True) for _ in range(self.WORKERS)]
            for thread in self._threads:thread.start()
        except Exception:
            self.closed=True;self.f.close();os.unlink(self.tmp);raise

    def _request(self,start,end,timeout=20):
        headers={**self.headers,'Range':f'bytes={start}-{end}','Accept-Encoding':'identity'}
        return urllib.request.urlopen(urllib.request.Request(self.url,headers=headers),timeout=timeout)
    def _probe_size(self):
        with self._request(0,0,timeout=6) as response:
            match=re.fullmatch(r'bytes 0-0/(\d+)',response.headers.get('Content-Range',''))
            return int(match.group(1)) if match else int(response.headers.get('Content-Length') or 0)
    def set_focus(self,position):
        with self.cond:self.focus=max(0,min(self.size-1,int(position)));self.cond.notify_all()
    def wait_chunk(self,index):
        if not 0<=index<self.n:return False
        deadline=time.monotonic()+35
        with self.cond:
            while not self.have[index] and not self.closed and not self.expired:
                if self._attempts.get(index,0)>=3 or time.monotonic()>=deadline:return False
                self.cond.wait(.2)
            return bool(self.have[index]) and not self.closed
    def _next(self):
        first=self.focus//self.CHUNK;last=min(self.n,first+max(1,self.AHEAD//self.CHUNK))
        for index in range(first,last):
            if not self.have[index] and index not in self.busy and self._attempts.get(index,0)<3:return index
        return None
    def _worker(self):
        while True:
            with self.cond:
                if self.closed or self.expired:return
                index=self._next()
                if index is None:
                    if all(self.have):return
                    self.cond.wait(.2);continue
                self.busy.add(index)
            start=index*self.CHUNK;end=min(self.size,start+self.CHUNK)-1
            success=False
            try:
                with self._request(start,end) as response:
                    expected=f'bytes {start}-{end}/{self.size}'
                    if response.status==206:
                        if response.headers.get('Content-Range')!=expected:raise OSError('Server returned the wrong stream range')
                    elif not (response.status==200 and start==0 and end==self.size-1):raise OSError('Server does not support seeking')
                    data=response.read(end-start+2)
                if len(data)!=end-start+1:raise OSError('Incomplete stream range')
                with self.flock:
                    if not self.closed:self.f.seek(start);self.f.write(data);self.f.flush();success=True
            except Exception as error:
                with self.cond:
                    self.fails+=1
                    if getattr(error,'code',None)==403:self.forbidden+=1;self.expired=True
            finally:
                with self.cond:
                    self.busy.discard(index)
                    if success:self.have[index]=1
                    else:self._attempts[index]=self._attempts.get(index,0)+1
                    self.cond.notify_all()
            if not success:
                with self.cond:
                    if not self.closed:self.cond.wait(.25)
    def close(self):
        with self.cond:
            if self.closed:return
            self.closed=True;self.cond.notify_all()
        self.server.shutdown();self.server.server_close()
        with self.flock:self.f.close()
        try:os.unlink(self.tmp)
        except FileNotFoundError:pass
