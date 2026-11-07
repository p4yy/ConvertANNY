"""Windows file metadata operations used by ConvertANNY actions."""
import os
import stat
from pathlib import Path


def unblock_files(paths,limit=2_000_000,progress=None,stop=None):
    """Remove download-zone metadata, retaining contents and original attributes."""
    checked=removed=failed=0;seen=set()
    def enumerate_files():
        for value in paths:
            source=Path(value)
            if source.is_file():yield source
            elif source.is_dir():
                for directory,subdirectories,names in os.walk(source,followlinks=False):
                    subdirectories[:]=[name for name in subdirectories if not Path(directory,name).is_symlink()]
                    for name in names:
                        path=Path(directory,name)
                        if path.is_file() and not path.is_symlink():yield path
    for source in enumerate_files():
        if checked>=max(0,int(limit)) or (stop and stop()):break
        identifier=os.path.normcase(os.path.abspath(source))
        if identifier in seen:continue
        seen.add(identifier);checked+=1
        if os.name=='nt':
            absolute=str(source.absolute())
            if not absolute.startswith('\\\\?\\'):
                absolute='\\\\?\\UNC\\'+absolute[2:] if absolute.startswith('\\\\') else '\\\\?\\'+absolute
            stream=absolute+':Zone.Identifier';original_mode=None
            try:
                try:os.remove(stream)
                except PermissionError:
                    original_mode=source.stat().st_mode
                    os.chmod(source,original_mode|stat.S_IWRITE)
                    os.remove(stream)
                removed+=1
            except FileNotFoundError:pass
            except OSError:failed+=1
            finally:
                if original_mode is not None:
                    try:os.chmod(source,original_mode)
                    except OSError:failed+=1
        if progress and checked%250==0:progress(checked)
    return checked,removed,failed
