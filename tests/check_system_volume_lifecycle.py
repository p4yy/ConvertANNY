"""Mocked COM lifecycle for system_volume, including partial interface failures."""
import ctypes
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import winsys


def main():
    events = []
    class Ole:
        def CoInitialize(self, _): events.append('initialize')
        def CoUninitialize(self): events.append('uninitialize')
        def CoCreateInstance(self, clsid, outer, context, iid, output):
            output._obj.value = 101
            return 0
    def call(pointer, index, *args, **kwargs):
        if index == 4: args[2]._obj.value = 102
        elif index == 3: args[3]._obj.value = 103
        elif index == 9: args[0]._obj.value = .625
        elif index == 15: args[0]._obj.value = 1
        elif index == 2:
            events.append(('release', pointer.value))
            if pointer.value == 102: raise RuntimeError('release test')
        return 0
    with patch.object(winsys, 'IS_WIN', True), \
         patch.object(ctypes, 'oledll', SimpleNamespace(ole32=Ole()), create=True), \
         patch.object(winsys, '_vcall', call), patch.object(winsys, 'log', lambda _: None):
        assert winsys.system_volume() == (.625, True)
    assert events == ['initialize', ('release', 103), ('release', 102), ('release', 101), 'uninitialize']
    print('Mocked system volume COM lifecycle passed')


if __name__ == '__main__': main()
