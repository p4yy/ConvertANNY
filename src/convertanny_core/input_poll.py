"""Virtual-key maps and low-latency Windows input sampling for the orbit."""
from __future__ import annotations
import ctypes
import sys
import time

IS_WINDOWS=sys.platform=='win32'
SYNTHETIC=0x44570001
VK_LBUTTON=0x01;VK_SPACE=0x20;VK_ESCAPE=0x1B
VK={"Shift":0x10,"Ctrl":0x11,"Alt":0x12,"CapsLock":0x14,"Win":0x5B,"Tab":0x09,"Space":VK_SPACE,
    "Insert":0x2D,"Delete":0x2E,"Home":0x24,"End":0x23,"PageUp":0x21,"PageDown":0x22,
    "Left":0x25,"Up":0x26,"Right":0x27,"Down":0x28,"Backspace":0x08,"Enter":0x0D,
    "LeftClick":0x01,"RightClick":0x02,"MiddleMouse":0x04,"Mouse4":0x05,"Mouse5":0x06,
    "`":0xC0,"-":0xBD,"=":0xBB,"[":0xDB,"]":0xDD,";":0xBA,"'":0xDE,",":0xBC,".":0xBE,"/":0xBF,"\\":0xDC,
    **{chr(value):value for value in range(0x41,0x5B)},**{str(value):0x30+value for value in range(10)},
    **{f'F{value}':0x6F+value for value in range(1,25)},**{f'Num{value}':0x60+value for value in range(10)}}
SYNTH_UNTIL=0.

if IS_WINDOWS:
    from ctypes import wintypes
    user32=ctypes.WinDLL('user32',use_last_error=True)
    class POINT(ctypes.Structure):_fields_=[('x',wintypes.LONG),('y',wintypes.LONG)]
    user32.GetAsyncKeyState.argtypes=[ctypes.c_int];user32.GetAsyncKeyState.restype=ctypes.c_short
    user32.GetSystemMetrics.argtypes=[ctypes.c_int];user32.GetSystemMetrics.restype=ctypes.c_int
    user32.GetCursorPos.argtypes=[ctypes.POINTER(POINT)];user32.GetCursorPos.restype=wintypes.BOOL
    user32.FindWindowW.argtypes=[wintypes.LPCWSTR,wintypes.LPCWSTR];user32.FindWindowW.restype=wintypes.HWND
    user32.FindWindowExW.argtypes=[wintypes.HWND,wintypes.HWND,wintypes.LPCWSTR,wintypes.LPCWSTR];user32.FindWindowExW.restype=wintypes.HWND
    user32.IsWindowVisible.argtypes=[wintypes.HWND];user32.IsWindowVisible.restype=wintypes.BOOL
    user32.GetForegroundWindow.restype=wintypes.HWND
    user32.GetClassNameW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int];user32.GetClassNameW.restype=ctypes.c_int
    user32.WindowFromPoint.argtypes=[POINT];user32.WindowFromPoint.restype=wintypes.HWND
    user32.GetAncestor.argtypes=[wintypes.HWND,ctypes.c_uint];user32.GetAncestor.restype=wintypes.HWND
else:user32=None


def combo_vks(spec):
    if not spec or spec=='None':return []
    pieces=[part for part in spec.split('+') if part] if spec!='+' else ['+']
    values=[VK.get(part) for part in pieces]
    return [] if None in values else values


def key_down(code):
    return bool(IS_WINDOWS and user32.GetAsyncKeyState(int(code))&0x8000)


def mouse_down():
    if not IS_WINDOWS:return False
    button=0x02 if user32.GetSystemMetrics(23) else VK_LBUTTON
    return key_down(button)


def cursor_pos():
    if not IS_WINDOWS:return (0,0)
    point=POINT()
    return (point.x,point.y) if user32.GetCursorPos(ctypes.byref(point)) else (0,0)


def drag_threshold():return max(4,user32.GetSystemMetrics(68)) if IS_WINDOWS else 4


def file_drag_active():
    if not IS_WINDOWS:return False
    window=user32.FindWindowW('SysDragImage',None)
    while window:
        if user32.IsWindowVisible(window):return True
        window=user32.FindWindowExW(None,window,'SysDragImage',None)
    return False


def foreground_hwnd():return (user32.GetForegroundWindow() or 0) if IS_WINDOWS else 0


def window_class(hwnd):
    if not IS_WINDOWS or not hwnd:return ''
    buffer=ctypes.create_unicode_buffer(256)
    if not user32.GetClassNameW(hwnd,buffer,256):return ''
    return buffer.value


def root_window_at(x,y):
    if not IS_WINDOWS:return 0
    child=user32.WindowFromPoint(POINT(int(x),int(y)))
    return int(user32.GetAncestor(child,2) or child or 0)


def other_keys_down(excluded):
    if not IS_WINDOWS:return False
    excluded=set(excluded);aliases={0x10:(0xA0,0xA1),0x11:(0xA2,0xA3),0x12:(0xA4,0xA5)}
    ignored={0x14,0x90,0x91,0xFF,0x07,0x0A,0x0B,0x0E,0x0F,0x16,0x1A,0x3A}
    for code in range(1,0xFF):
        if code in excluded or code in ignored:continue
        if code in aliases and any(item in excluded for item in aliases[code]):continue
        if any(code in values and modifier in excluded for modifier,values in aliases.items()):continue
        if key_down(code):return True
    return False


def click_at_cursor():
    global SYNTH_UNTIL
    if not IS_WINDOWS:return
    from ctypes import wintypes
    SYNTH_UNTIL=time.monotonic()+.3
    held=[code for code in (0xA0,0xA1,0xA2,0xA3,0xA4,0xA5,0x5B,0x5C) if key_down(code)]
    extended=lambda code:1 if code in (0xA3,0xA5,0x5B,0x5C) else 0
    user32.keybd_event.argtypes=[wintypes.BYTE,wintypes.BYTE,wintypes.DWORD,ctypes.c_size_t]
    user32.mouse_event.argtypes=[wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,ctypes.c_size_t]
    if any(code in (0xA4,0xA5,0x5B,0x5C) for code in held):
        user32.keybd_event(0xE8,0,0,SYNTHETIC);user32.keybd_event(0xE8,0,2,SYNTHETIC)
    for code in held:user32.keybd_event(code,0,extended(code)|2,SYNTHETIC)
    user32.mouse_event(0x0002,0,0,0,SYNTHETIC);user32.mouse_event(0x0004,0,0,0,SYNTHETIC)
    for code in held:user32.keybd_event(code,0,extended(code),SYNTHETIC)
    SYNTH_UNTIL=time.monotonic()+.25
