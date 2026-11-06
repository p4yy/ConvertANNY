"""Verify Windows hook event routing without installing global system hooks."""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from convertanny_core.win_hooks import WheelHook


def check():
    hook=WheelHook(lambda delta:None)
    opened=[];hook.on_ctrl_double=opened.append;hook.ctrl_double_enabled=lambda:True
    hook._is_shell_window=lambda point:42
    mouse=SimpleNamespace(pt=SimpleNamespace(x=120,y=80))
    settings=dict(double_click_ms=500,double_click_size=(6,6),control_down=True)
    assert not hook.route_mouse(0x0201,mouse,now_ms=100,**settings)
    assert hook.route_mouse(0x0201,mouse,now_ms=300,**settings)
    assert hook.state.swallowed_left_up and opened==[42]
    assert hook.route_mouse(0x0202,mouse,now_ms=310,**settings)
    assert not hook.route_mouse(0x0201,mouse,now_ms=1000,**settings)
    assert not hook.route_mouse(0x0201,mouse,now_ms=1600,**settings)
    hook.on_click=lambda button,down:button==2
    no_control={**settings,'control_down':False}
    assert hook.route_mouse(0x0204,mouse,now_ms=2000,**no_control)
    assert hook.route_mouse(0x0205,mouse,now_ms=2001,**no_control)
    hook.on_ctrl_double=lambda hwnd:opened.append(hwnd)
    enter=SimpleNamespace(vkCode=0x0d)
    assert hook.route_key(0x0100,enter,control_down=True,shift_down=False,alt_down=False,file_list_window=lambda:88)
    assert hook.route_key(0x0100,enter,control_down=True,shift_down=False,alt_down=False,file_list_window=lambda:88)
    assert hook.route_key(0x0101,enter,control_down=True,shift_down=False,alt_down=False,file_list_window=lambda:88)
    assert opened==[42,88]
    media=[];hook.on_volume_key=media.append
    assert not hook.route_key(0x0100,SimpleNamespace(vkCode=0xaf),control_down=False,shift_down=False,alt_down=False)
    assert media==[0xaf]
    hook.start();hook.stop()
    print('Low-level hook event routing, paired releases and no-install lifecycle passed')


if __name__=='__main__':check()
