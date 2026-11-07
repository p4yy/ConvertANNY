"""Streaming file digests with cancellation and byte-level progress reporting."""
import hashlib
from pathlib import Path

from .model import Cancelled


def sha256_file(path,*,stop=lambda:False,on_progress=None,chunk_size=1024*1024):
    source=Path(path);size=source.stat().st_size;done=0;digest=hashlib.sha256()
    with source.open('rb') as stream:
        while True:
            if stop():raise Cancelled('Checksum cancelled')
            block=stream.read(chunk_size)
            if not block:break
            digest.update(block);done+=len(block)
            if on_progress:on_progress(done,size)
    if on_progress:on_progress(size,size)
    return digest.hexdigest()


def sha256_batch(paths,*,stop=lambda:False,on_progress=None):
    files=[Path(path) for path in paths if Path(path).is_file()]
    output=[]
    for index,path in enumerate(files):
        if stop():raise Cancelled('Checksum cancelled')
        def update(done,total):
            if on_progress:on_progress(index, len(files), done, total, path.name)
        output.append((path,sha256_file(path,stop=stop,on_progress=update)))
    return output
