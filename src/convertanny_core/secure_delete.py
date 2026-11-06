"""Best-effort local overwrite and deletion for the explicit Shred action."""
from pathlib import Path
import os
from uuid import uuid4

from .model import ConversionError


def shred_path(value,*,random_bytes=os.urandom,block_size=1024*1024):
    path=Path(value)
    if path.is_symlink():
        path.unlink();return
    if path.is_dir():
        # Do not traverse junctions/symlinks into unrelated directories.
        for entry in path.iterdir():
            shred_path(entry,random_bytes=random_bytes,block_size=block_size)
        path.rmdir();return
    if not path.is_file():raise ConversionError(f'Cannot shred missing item: {path.name}')
    size=path.stat().st_size
    try:
        with path.open('r+b',buffering=0) as stream:
            remaining=size
            while remaining:
                amount=min(block_size,remaining);stream.write(random_bytes(amount));remaining-=amount
            stream.flush();os.fsync(stream.fileno());stream.truncate(0)
        temporary=path.with_name(uuid4().hex)
        os.rename(path,temporary)
        temporary.unlink()
    except OSError as error:
        raise ConversionError(f'Could not securely overwrite {path.name}: {error}') from error
