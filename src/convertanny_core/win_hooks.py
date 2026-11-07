"""Process-wide Windows pointer and keyboard hooks used by ConvertANNY gestures."""
from __future__ import annotations

import ctypes
import sys
import threading
from dataclasses import dataclass
from ctypes import wintypes

from . import input_poll


EXPLORER_WINDOWS={'CabinetWClass','ExploreWClass','Progman','WorkerW'}
FILE_LIST_WINDOWS={'DirectUIHWND','SysListView32'}
MOUSE_BUTTONS={0x0201:(1,True),0x0202:(1,False),0x0204:(2,True),0x0205:(2,False)}
MEDIA_KEYS={0xAD,0xAE,0xAF}


@dataclass
class HookGestureState:
    swallowed_buttons:set
    swallowed_left_up:bool=False
    swallowed_enter_up:bool=False
    enter_held:bool=False
    prior_control_click:tuple|None=None

    @classmethod
    def create(cls):return cls(set())


class WheelHook:
    """Install low-level hooks on a dedicated message thread and route compact events."""
    def __init__(self,on_wheel,should_swallow=lambda:False,on_ctrl_double=None,ctrl_double_enabled=lambda:False):
        self.on_wheel=on_wheel;self.should_swallow=should_swallow
        self.on_ctrl_double=on_ctrl_double;self.ctrl_double_enabled=ctrl_double_enabled
        self.on_volume_key=None;self.on_click=None
        self.state=HookGestureState.create();self._thread=None;self._thread_id=0
        self._stop=threading.Event();self._ready=threading.Event();self._mouse_proc=None;self._keyboard_proc=None

    def start(self):
        if sys.platform!='win32' or (self._thread and self._thread.is_alive()):return
        self._stop.clear();self._ready.clear();self._thread=threading.Thread(target=self._message_loop,name='ConvertANNYInput',daemon=True)
        self._thread.start();self._ready.wait(timeout=1)

    def stop(self):
        self._stop.set();self._ready.wait(timeout=1);thread_id=self._thread_id
        if thread_id and sys.platform=='win32':ctypes.WinDLL('user32').PostThreadMessageW(thread_id,0x0012,0,0)
        thread=self._thread
        if thread and thread is not threading.current_thread():thread.join(timeout=2)

    def _is_shell_window(self,point):
        hwnd=input_poll.root_window_at(point.x,point.y)
        return hwnd if input_poll.window_class(hwnd) in EXPLORER_WINDOWS else 0

    def route_mouse(self,message,event,*,now_ms,double_click_ms,double_click_size,control_down,synthetic=False):
        state=self.state
        if synthetic:return False
        if message in MOUSE_BUTTONS:
            button,pressed=MOUSE_BUTTONS[message]
            if not pressed and button in state.swallowed_buttons:
                state.swallowed_buttons.discard(button);return True
            if pressed and self.on_click and self.on_click(button,True):
                state.swallowed_buttons.add(button);return True
        if message==0x0202 and state.swallowed_left_up:
            state.swallowed_left_up=False;return True
        if message!=0x0201 or self.on_ctrl_double is None:return False
        if not control_down or not self.ctrl_double_enabled():state.prior_control_click=None;return False
        hwnd=self._is_shell_window(event.pt)
        if not hwnd:state.prior_control_click=None;return False
        previous=state.prior_control_click
        if previous:
            when,x,y,target=previous
            if (now_ms-when)&0xffffffff<=double_click_ms and target==hwnd and abs(event.pt.x-x)<=double_click_size[0] and abs(event.pt.y-y)<=double_click_size[1]:
                state.prior_control_click=None;state.swallowed_left_up=True;self.on_ctrl_double(hwnd);return True
        state.prior_control_click=(now_ms,event.pt.x,event.pt.y,hwnd);return False

    def route_key(self,message,event,*,control_down,shift_down,alt_down,file_list_window=None):
        state=self.state;pressed=message in (0x0100,0x0104);released=message==0x0101
        if pressed and self.on_volume_key and event.vkCode in MEDIA_KEYS:self.on_volume_key(int(event.vkCode))
        if event.vkCode!=0x0d or self.on_ctrl_double is None or message not in (0x0100,0x0101):return False
        if released:
            state.enter_held=False
            if state.swallowed_enter_up:state.swallowed_enter_up=False;return True
        if not (control_down and not shift_down and not alt_down and self.ctrl_double_enabled()):return False
        target=file_list_window() if file_list_window else 0
        if not target:return False
        state.swallowed_enter_up=True
        if not state.enter_held:
            state.enter_held=True;self.on_ctrl_double(target)
        return True

    def _message_loop(self):
        if sys.platform!='win32':return
        user32=ctypes.WinDLL('user32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        self._thread_id=kernel.GetCurrentThreadId()
        # Force creation of this thread's queue before stop() posts WM_QUIT.
        class BootstrapMessage(ctypes.Structure):
            _fields_=[('hwnd',wintypes.HWND),('message',wintypes.UINT),('wParam',wintypes.WPARAM),('lParam',wintypes.LPARAM),('time',wintypes.DWORD),('point',input_poll.POINT),('private',wintypes.DWORD)]
        bootstrap=BootstrapMessage();user32.PeekMessageW(ctypes.byref(bootstrap),None,0,0,0)
        self._ready.set()
        class MouseEvent(ctypes.Structure):
            _fields_=[('pt',input_poll.POINT),('mouseData',wintypes.DWORD),('flags',wintypes.DWORD),('time',wintypes.DWORD),('extra',ctypes.c_size_t)]
        class KeyboardEvent(ctypes.Structure):
            _fields_=[('vkCode',wintypes.DWORD),('scanCode',wintypes.DWORD),('flags',wintypes.DWORD),('time',wintypes.DWORD),('extra',ctypes.c_size_t)]
        class Rect(ctypes.Structure):_fields_=[('left',ctypes.c_long),('top',ctypes.c_long),('right',ctypes.c_long),('bottom',ctypes.c_long)]
        class GuiThread(ctypes.Structure):
            _fields_=[('size',wintypes.DWORD),('flags',wintypes.DWORD),('active',wintypes.HWND),('focus',wintypes.HWND),('capture',wintypes.HWND),('menu',wintypes.HWND),('move',wintypes.HWND),('caret',wintypes.HWND),('rect',Rect)]
        result=ctypes.c_ssize_t;callback_type=ctypes.WINFUNCTYPE(result,ctypes.c_int,wintypes.WPARAM,wintypes.LPARAM)
        user32.CallNextHookEx.restype=result;user32.CallNextHookEx.argtypes=[wintypes.HHOOK,ctypes.c_int,wintypes.WPARAM,wintypes.LPARAM]
        user32.SetWindowsHookExW.restype=wintypes.HHOOK;user32.SetWindowsHookExW.argtypes=[ctypes.c_int,callback_type,wintypes.HINSTANCE,wintypes.DWORD]
        user32.GetWindowThreadProcessId.restype=wintypes.DWORD;user32.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
        user32.GetGUIThreadInfo.argtypes=[wintypes.DWORD,ctypes.POINTER(GuiThread)];user32.GetGUIThreadInfo.restype=wintypes.BOOL
        user32.GetDoubleClickTime.restype=wintypes.UINT
        size=(max(4,user32.GetSystemMetrics(36)),max(4,user32.GetSystemMetrics(37)))
        double_time=user32.GetDoubleClickTime()
        def next_hook(code,message,payload):return user32.CallNextHookEx(None,code,message,payload)
        def mouse_callback(code,message,payload):
            if code<0:return next_hook(code,message,payload)
            try:
                event=ctypes.cast(payload,ctypes.POINTER(MouseEvent)).contents
                swallow=self.route_mouse(message,event,now_ms=event.time,double_click_ms=double_time,
                    double_click_size=size,control_down=input_poll.key_down(0x11),
                    synthetic=event.extra==input_poll.SYNTHETIC)
                if message==0x020a:
                    delta=ctypes.c_short((event.mouseData>>16)&0xffff).value
                    if self.should_swallow():swallow=True
                    self.on_wheel(delta)
                if swallow:return 1
            except Exception:pass
            return next_hook(code,message,payload)
        def focused_file_list():
            foreground=input_poll.foreground_hwnd()
            if not foreground or input_poll.window_class(foreground) not in EXPLORER_WINDOWS:return 0
            info=GuiThread();info.size=ctypes.sizeof(info)
            ui_thread=user32.GetWindowThreadProcessId(foreground,None)
            if not user32.GetGUIThreadInfo(ui_thread,ctypes.byref(info)) or not info.focus:return 0
            return foreground if input_poll.window_class(info.focus) in FILE_LIST_WINDOWS else 0
        def keyboard_callback(code,message,payload):
            if code<0:return next_hook(code,message,payload)
            try:
                event=ctypes.cast(payload,ctypes.POINTER(KeyboardEvent)).contents
                swallow=self.route_key(message,event,control_down=input_poll.key_down(0x11),
                    shift_down=input_poll.key_down(0x10),alt_down=input_poll.key_down(0x12),file_list_window=focused_file_list)
                if swallow:return 1
            except Exception:pass
            return next_hook(code,message,payload)
        self._mouse_proc=callback_type(mouse_callback);self._keyboard_proc=callback_type(keyboard_callback)
        module=kernel.GetModuleHandleW(None)
        hooks=[user32.SetWindowsHookExW(14,self._mouse_proc,module,0),user32.SetWindowsHookExW(13,self._keyboard_proc,module,0)]
        if not all(hooks):
            for hook in hooks:
                if hook:user32.UnhookWindowsHookEx(hook)
            self._thread_id=0;return
        class Message(ctypes.Structure):
            _fields_=[('hwnd',wintypes.HWND),('message',wintypes.UINT),('wParam',wintypes.WPARAM),('lParam',wintypes.LPARAM),('time',wintypes.DWORD),('point',input_poll.POINT),('private',wintypes.DWORD)]
        message=Message();user32.GetMessageW.argtypes=[ctypes.POINTER(Message),wintypes.HWND,wintypes.UINT,wintypes.UINT];user32.GetMessageW.restype=ctypes.c_int
        user32.TranslateMessage.argtypes=[ctypes.POINTER(Message)];user32.DispatchMessageW.argtypes=[ctypes.POINTER(Message)]
        try:
            while not self._stop.is_set():
                status=user32.GetMessageW(ctypes.byref(message),None,0,0)
                if status<=0:break
                user32.TranslateMessage(ctypes.byref(message));user32.DispatchMessageW(ctypes.byref(message))
        finally:
            for hook in hooks:
                if hook:user32.UnhookWindowsHookEx(hook)
            self._thread_id=0
