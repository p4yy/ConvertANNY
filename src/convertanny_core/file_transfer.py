"""Collision-safe file copy and move operations for user-selected batches."""
from pathlib import Path
import os
import shutil
from uuid import uuid4

from .model import Cancelled,ConversionError


def _unique_name(name,occupied):
    path=Path(name)
    suffix=''.join(path.suffixes)
    stem=name[:-len(suffix)] if suffix else name
    index=1
    while True:
        candidate=name if index==1 else f'{stem} ({index}){suffix}'
        if candidate not in occupied:return candidate
        index+=1


def _publish_file(source,target,stop):
    created=False
    try:
        with source.open('rb') as reader,target.open('xb') as writer:
            created=True
            while True:
                if stop():raise Cancelled('File transfer cancelled')
                block=reader.read(1024*1024)
                if not block:break
                writer.write(block)
            writer.flush();os.fsync(writer.fileno())
        shutil.copystat(source,target,follow_symlinks=True)
    except Exception:
        if created:target.unlink(missing_ok=True)
        raise


def _copy_tree(source,target,stop):
    if stop():raise Cancelled('File transfer cancelled')
    target.mkdir()
    try:
        for child in source.iterdir():
            if stop():raise Cancelled('File transfer cancelled')
            destination=target/child.name
            if child.is_symlink():raise ConversionError(f'Symbolic link skipped: {child.name}')
            if child.is_dir():_copy_tree(child,destination,stop)
            elif child.is_file():_publish_file(child,destination,stop)
        shutil.copystat(source,target,follow_symlinks=True)
    except Exception:
        shutil.rmtree(target,ignore_errors=True)
        raise


def transfer_items(sources,destination,*,move=False,stop=lambda:False,on_progress=None):
    directory=Path(destination)
    if not directory.is_dir():raise ConversionError('Choose an existing destination folder')
    inputs=[Path(source) for source in sources]
    if any(not source.exists() for source in inputs):raise ConversionError('One or more selected items no longer exist')
    resolved=directory.resolve()
    if any(source.resolve()==resolved or (source.is_dir() and source.resolve() in resolved.parents) for source in inputs):
        raise ConversionError('The destination cannot be inside a selected folder')
    occupied={path.name for path in directory.iterdir()};completed=[];failures=[]
    for index,source in enumerate(inputs):
        if stop():break
        name=_unique_name(source.name,occupied);target=directory/name
        try:
            if source.is_symlink():raise ConversionError('Symbolic links are not copied as folder contents')
            if source.is_dir():
                _copy_tree(source,target,stop)
                if move:shutil.rmtree(source)
            elif move:
                _publish_file(source,target,stop)
                if stop():target.unlink(missing_ok=True);raise Cancelled('File transfer cancelled')
                source.unlink()
            else:_publish_file(source,target,stop)
            occupied.add(name);completed.append(target)
        except Cancelled:raise
        except Exception as error:failures.append((source.name,str(error) or type(error).__name__))
        if on_progress:on_progress(index+1,len(inputs),len(completed))
    if failures and not completed:raise ConversionError(failures[0][1])
    return completed,failures
