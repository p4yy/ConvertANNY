"""Verify shred behavior only against disposable test paths."""
import sys,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from convertanny_core.secure_delete import shred_path
from convertanny_core.model import ConversionError


def check():
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'tmp') as folder:
        root=Path(folder);item=root/'secret.bin';item.write_bytes(bytes(range(256))*3000)
        shred_path(item);assert not item.exists()
        empty=root/'empty';empty.touch();shred_path(empty);assert not empty.exists()
        directory=root/'directory';directory.mkdir();(directory/'nested').write_text('disposable')
        shred_path(directory);assert not directory.exists()
        with patch('convertanny_core.secure_delete.Path.is_symlink',return_value=True),patch(
                'convertanny_core.secure_delete.Path.unlink') as unlink:
            shred_path(root/'link');unlink.assert_called_once_with()
        try:shred_path(root/'missing')
        except ConversionError:pass
        else:raise AssertionError('Missing path accepted')
    print('Shred file, directory, symlink and missing-path checks passed on disposable test data')


if __name__=='__main__':check()
