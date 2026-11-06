"""ConvertANNY rename planning, validation and recoverable execution."""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


@dataclass
class RenameOptions:
    name: str = ""
    find: str = ""
    replacement: str = ""
    numbered: bool = False
    start: int = 1
    padding: int = 2
    dated: bool = False
    date_source: str = "modified"
    date_format: str = "%Y-%m-%d"
    before: bool = False
    numerals: str = "keep"
    case: str = "keep"


def file_date(path,source):
    if source=='today':return dt.date.today()
    if source=='taken':
        try:
            from PIL import Image
            with Image.open(path) as image:
                exif=image.getexif()
                date=(exif.get_ifd(34665) or {}).get(36867) or exif.get(306)
            if date:return dt.datetime.strptime(str(date)[:10],'%Y:%m:%d').date()
        except (OSError,ValueError,TypeError,KeyError):pass
    return dt.date.fromtimestamp(Path(path).stat().st_mtime)


def plan_names(paths,options: RenameOptions):
    results=[]
    for index,source in enumerate(map(Path,paths)):
        stem,suffix=(source.name,'') if source.is_dir() else (source.stem,source.suffix)
        name=options.name.strip() or stem
        if options.find:name=name.replace(options.find,options.replacement)
        additions=[]
        if options.dated:additions.append(file_date(source,options.date_source).strftime(options.date_format))
        if options.numbered:additions.append(str(options.start+index).zfill(options.padding))
        pieces=[*additions,name] if options.before else [name,*additions]
        name=' '.join(pieces)
        if options.case in ('lower','upper','title'):name=getattr(name,options.case)()
        if options.numerals=='ar':name=name.translate(str.maketrans('0123456789','٠١٢٣٤٥٦٧٨٩'))
        elif options.numerals=='en':name=name.translate(str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹','01234567890123456789'))
        name=re.sub(r'[<>:"/\\|?*\x00-\x1f]','',name).strip().rstrip('.') or stem
        results.append(source.with_name(name+suffix))
    return results


def validate_plan(sources,destinations):
    sources,destinations=list(map(Path,sources)),list(map(Path,destinations))
    if len(sources)!=len(destinations):raise OSError('Rename plan does not match the selection')
    identity=lambda path:str(path.absolute()).casefold()
    originals={identity(path) for path in sources}
    targets=[identity(path) for path in destinations]
    if len(originals)!=len(sources):raise OSError('The same source was selected more than once')
    if len(set(targets))!=len(targets):raise OSError('Several files have the same destination name')
    for source,target in zip(sources,destinations):
        if not source.exists():raise OSError(f'File not found: {source.name}')
        if source.parent!=target.parent:raise OSError('Batch rename must keep files in their original folders')
        if target.exists() and identity(target) not in originals:raise FileExistsError(f'File already exists: {target.name}')
        if target.stem.upper() in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}:
            raise OSError(f'Windows reserves the name: {target.name}')
    for source in sources:
        if source.is_dir() and any(other!=source and other.is_relative_to(source) for other in sources):
            raise OSError('Rename a folder and its selected contents in separate operations')


def apply_plan(sources,destinations):
    sources,destinations=list(map(Path,sources)),list(map(Path,destinations))
    validate_plan(sources,destinations)
    changes=[(source,target) for source,target in zip(sources,destinations) if str(source)!=str(target)]
    staged=[];published=[]
    try:
        for source,target in changes:
            temporary=source.with_name('.convertanny-rename-'+uuid4().hex)
            source.rename(temporary)
            staged.append((source,temporary,target))
        for source,temporary,target in staged:
            if target.exists():raise FileExistsError(f'File already exists: {target.name}')
            temporary.rename(target);published.append((source,temporary,target))
    except OSError as error:
        recovery=[]
        for source,temporary,target in reversed(published):
            try:target.rename(temporary)
            except OSError as failure:recovery.append(str(failure))
        for source,temporary,target in reversed(staged):
            if temporary.exists():
                try:temporary.rename(source)
                except OSError as failure:recovery.append(str(failure))
        if recovery:raise OSError(f'{error}. Recovery needs attention: '+ '; '.join(recovery)) from error
        raise
    return [(str(source),str(target)) for source,target in changes]


def file_sha256(path,progress=None):
    source=Path(path);total=source.stat().st_size;processed=0;digest=hashlib.sha256()
    with source.open('rb') as stream:
        while True:
            block=stream.read(1024*1024)
            if not block:break
            digest.update(block);processed+=len(block)
            if progress:progress(processed/max(1,total))
    return digest.hexdigest()
