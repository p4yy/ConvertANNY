"""Exercise copy/move collisions and cancellation without touching user files."""
import shutil,sys,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from convertanny_core.file_transfer import transfer_items
from convertanny_core.model import ConversionError,Cancelled
from convertanny_core.paths import atomic_write


def check():
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'tmp') as location:
        root=Path(location);source=root/'source';target=root/'target';source.mkdir();target.mkdir()
        item=source/'a.tar.gz';item.write_text('contents');(target/item.name).write_text('existing')
        output,errors=transfer_items([item],target)
        assert not errors and output[0].name=='a (2).tar.gz' and output[0].read_text()=='contents'
        moved,errors=transfer_items([item],target,move=True)
        assert not errors and not item.exists() and moved[0].name=='a (3).tar.gz'
        bundle=source/'bundle';bundle.mkdir();(bundle/'inside.txt').write_text('nested')
        copied,errors=transfer_items([bundle],target)
        assert not errors and (copied[0]/'inside.txt').read_text()=='nested' and bundle.exists()
        nested=bundle/'deeper';nested.mkdir();(nested/'payload').write_bytes(b'contents')
        shutil.rmtree(copied[0]);counter=[0]
        def stop():
            counter[0]+=1
            return counter[0]>4
        try:transfer_items([bundle],target,stop=stop)
        except Cancelled:pass
        else:raise AssertionError('Folder copy ignored cancellation')
        assert bundle.exists() and not (target/'bundle').exists()
        link=bundle/'symbolic-link';link.touch();original=Path.is_symlink
        with patch.object(Path,'is_symlink',lambda path:True if path==link else original(path)):
            try:transfer_items([bundle],target)
            except ConversionError:pass
            else:raise AssertionError('Folder copy followed a symbolic link')
        link.unlink()
        before=set(target.iterdir());pending=source/'pending.txt';pending.write_text('keep')
        outputs,errors=transfer_items([pending],target,stop=lambda:True)
        assert outputs==[] and errors==[] and pending.exists() and set(target.iterdir())==before
        try:transfer_items([bundle],bundle/'child')
        except ConversionError:pass
        else:raise AssertionError('Nested target accepted')
        denied=target/'denied-output.txt'
        with patch('convertanny_core.paths.os.open',side_effect=PermissionError('access denied')):
            try:atomic_write(denied,lambda temporary:temporary.write_text('partial',encoding='utf-8'))
            except ConversionError as error:
                assert 'Preferences → Files & jobs' in str(error)
                assert 'read-only or in use' in str(error)
            else:raise AssertionError('Permission errors were not explained to the user')
        assert not denied.exists() and not list(target.glob('.denied-output.*.part'))
    print('File copy/move collision, folder, cancellation, and source preservation checks passed')


if __name__=='__main__':check()
