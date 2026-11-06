"""Check streamed SHA-256 output, byte progress, batches and cancellation."""
import hashlib,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from convertanny_core.checksums import sha256_file,sha256_batch
from convertanny_core.model import Cancelled


def check():
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'tmp') as folder:
        path=Path(folder)/'sample.bin';data=bytes(range(256))*10000;path.write_bytes(data)
        expected=hashlib.sha256(data).hexdigest()
        assert sha256_file(path,chunk_size=8192)==expected
        progress=[];assert sha256_batch([path],on_progress=lambda *args:progress.append(args))[0][1]==expected
        assert len(progress)>1 and progress[-1][2:4]==(len(data),len(data))
        try:sha256_file(path,stop=lambda:True)
        except Cancelled:pass
        else:raise AssertionError('Cancelled checksum continued')
    print('Streaming SHA-256 digest, progress and cancellation passed')


if __name__=='__main__':check()
