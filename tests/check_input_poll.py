"""Exercise ConvertANNY shortcut decoding and mocked Windows input samples."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from convertanny_core import input_poll as sample


def check():
    assert sample.combo_vks('Ctrl+Shift+F12')==[0x11,0x10,0x7B]
    assert sample.combo_vks('CapsLock+Space')==[0x14,0x20]
    assert sample.combo_vks('None')==[] and sample.combo_vks('Unknown+F1')==[]
    assert sample.combo_vks('+')==[]
    if sample.IS_WINDOWS:
        with patch.object(sample.user32,'GetAsyncKeyState',side_effect=lambda code:-32768 if code==0x41 else 0):
            assert sample.key_down(0x41) and not sample.key_down(0x42)
        with patch.object(sample.user32,'GetSystemMetrics',side_effect=lambda code:1 if code==68 else 0):
            assert sample.drag_threshold()==4
        with patch.object(sample.user32,'GetSystemMetrics',return_value=24):
            with patch.object(sample.user32,'GetAsyncKeyState',side_effect=lambda code:-32768 if code==2 else 0):
                assert sample.mouse_down()
        with patch.object(sample.user32,'GetSystemMetrics',return_value=0):
            with patch.object(sample.user32,'GetAsyncKeyState',side_effect=lambda code:-32768 if code==1 else 0):
                assert sample.mouse_down()
        with patch.object(sample.user32,'FindWindowW',return_value=13),patch.object(sample.user32,'IsWindowVisible',return_value=1):
            assert sample.file_drag_active()
        with patch.object(sample.user32,'FindWindowW',return_value=0):assert not sample.file_drag_active()
        def class_name(hwnd,buffer,size):buffer.value='CabinetWClass';return len(buffer.value)
        with patch.object(sample.user32,'GetClassNameW',side_effect=class_name):
            assert sample.window_class(101)=='CabinetWClass'
        assert len(sample.cursor_pos())==2 and sample.drag_threshold()>=4
    else:
        assert sample.cursor_pos()==(0,0) and sample.drag_threshold()==4
        assert not sample.key_down(0x41) and not sample.file_drag_active()
    print('Shortcut decoding and Windows key, pointer, drag, threshold and window probes passed')


if __name__=='__main__':check()
