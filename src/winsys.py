"""Windows-specific plumbing: input polling, Explorer selection, shell integration."""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import uuid
from convertanny_core.input_poll import (VK,VK_LBUTTON,VK_SPACE,VK_ESCAPE,user32,POINT,SYNTHETIC,
    combo_vks,key_down,mouse_down,cursor_pos,drag_threshold,file_drag_active,foreground_hwnd,
    window_class,root_window_at,click_at_cursor,other_keys_down)
import convertanny_core.input_poll as _input_poll
from convertanny_core.win_hooks import WheelHook
from pathlib import Path
from convertanny_core.windows_integration import (app_command, icon_path, set_startup, startup_enabled,
    set_context_menu, context_menu_enabled, sendto_enabled, set_sendto, cli_command_file,
    ensure_cli_command, open_cli_window)

IS_WIN = sys.platform == "win32"

VK_LBUTTON=0x01
VK_SPACE=0x20
VK_ESCAPE=0x1B

if IS_WIN:
    from ctypes import wintypes


class _GUID(ctypes.Structure):
    """In-memory Windows GUID layout used by the Core Audio COM interfaces."""
    _fields_ = [("a", ctypes.c_uint32), ("b", ctypes.c_uint16),
                ("c", ctypes.c_uint16), ("d", ctypes.c_ubyte * 8)]


def _guid(text):
    parsed = uuid.UUID(str(text).strip("{}"))
    tail = (ctypes.c_ubyte * 8).from_buffer_copy(parsed.bytes[8:])
    return _GUID(parsed.time_low, parsed.time_mid, parsed.time_hi_version, tail)


def _vcall(ptr, index, *args, argtypes=()):
    """Call method number `index` of a COM interface pointer."""
    vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    fn = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)(vtbl[index])
    result = fn(ptr, *args)
    if result < 0:
        raise OSError(f"COM method {index} failed with HRESULT 0x{result & 0xFFFFFFFF:08X}")
    return result


def system_volume():
    """Windows' speaker volume as (0..1, muted), or None. Core Audio IAudioEndpointVolume through plain ctypes."""
    if not IS_WIN:
        return None
    ole32 = ctypes.oledll.ole32
    initialized = False
    try:
        ole32.CoInitialize(None)
        initialized = True
    except OSError:
        pass
    enum, dev, vol = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    try:
        ole32.CoCreateInstance(ctypes.byref(_guid("{BCDE0395-E52F-467C-8E3D-C4579291692E}")), None, 23,
                               ctypes.byref(_guid("{A95664D2-9614-4F35-A746-DE8DB63617E6}")), ctypes.byref(enum))
        _vcall(enum, 4, 0, 1, ctypes.byref(dev),                                  # GetDefaultAudioEndpoint(render, multimedia)
               argtypes=(ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)))
        iid = _guid("{5CDF2C82-841E-4546-9722-0CF74078229A}")
        _vcall(dev, 3, ctypes.byref(iid), 23, None, ctypes.byref(vol),           # Activate(IAudioEndpointVolume)
               argtypes=(ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)))
        level, muted = ctypes.c_float(), ctypes.c_int()
        _vcall(vol, 9, ctypes.byref(level), argtypes=(ctypes.POINTER(ctypes.c_float),))   # GetMasterVolumeLevelScalar
        _vcall(vol, 15, ctypes.byref(muted), argtypes=(ctypes.POINTER(ctypes.c_int),))     # GetMute
        return max(0.0, min(1.0, level.value)), bool(muted.value)
    except Exception as e:
        log(f"system volume: {e}")
        return None
    finally:
        for p in (vol, dev, enum):
            if p.value:
                try:
                    _vcall(p, 2)                                                   # Release
                except Exception as e:
                    log(f"system volume release: {e}")
        if initialized:
            ole32.CoUninitialize()
















# ----------------------------------------------------------------------------
# Explorer selection
# ----------------------------------------------------------------------------
_FULL_MENU_KEY = r"Software\Classes\CLSID\{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}\InprocServer32"


def full_menu_enabled() -> bool:
    """Windows 11: is the full right-click menu (the Windows 10 one, no 'Show more options') turned on?"""
    if not IS_WIN:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _FULL_MENU_KEY):
            return True
    except OSError:
        return False


def set_full_menu(enabled: bool) -> None:
    """Windows' own switch for the full right-click menu, for this user only. Explorer must restart to see it."""
    import winreg
    if enabled:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _FULL_MENU_KEY) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "")
    else:
        for sub in (_FULL_MENU_KEY, _FULL_MENU_KEY.rsplit("\\", 1)[0]):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
            except OSError:
                pass
    log(f"full right-click menu: {enabled}")


def restart_explorer() -> None:
    import subprocess
    subprocess.run(["taskkill", "/f", "/im", "explorer.exe"], capture_output=True, creationflags=0x08000000)
    subprocess.Popen([os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "explorer.exe")])


def windows_11() -> bool:
    import sys
    return IS_WIN and sys.getwindowsversion().build >= 22000


def bring_to_front(hwnd: int) -> None:
    """Put a window above the others once (so it is seen), without making it stay on top."""
    if not IS_WIN or not hwnd:
        return
    try:
        flags = 0x0001 | 0x0002 | 0x0040          # NOSIZE | NOMOVE | SHOWWINDOW
        sw = user32.SetWindowPos
        sw.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        sw(hwnd, wintypes.HWND(-1), 0, 0, 0, 0, flags)      # HWND_TOPMOST …
        sw(hwnd, wintypes.HWND(-2), 0, 0, 0, 0, flags)      # … then back to normal: it stays in front for now
        user32.SetForegroundWindow(hwnd)
    except Exception as e:
        log(f"bring to front: {e}")


def unblock(paths, limit=2_000_000, progress=None, stop=None):
    from convertanny_core.windows_files import unblock_files
    return unblock_files(paths,limit=limit,progress=progress,stop=stop)


def set_foreground(hwnd: int) -> None:
    """Make this window the foreground window (allowed right after the user clicked one of ours)."""
    if not IS_WIN or not hwnd:
        return
    try:
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow(hwnd)
    except Exception as e:
        log(f"foreground: {e}")


def root_window_at(x, y):
    return _input_poll.root_window_at(x,y)


def window_title(hwnd: int) -> str:
    if not IS_WIN or not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(ctypes.c_void_p(hwnd), buf, 512)
    return buf.value


def _active_tab_hwnd(frame: int) -> int:
    """Windows 11 Explorer tabs: the visible ShellTabWindowClass child is the active tab."""
    from ctypes import wintypes
    user32.FindWindowExW.restype = wintypes.HWND
    child = user32.FindWindowExW(frame, None, "ShellTabWindowClass", None)
    while child:
        if user32.IsWindowVisible(child):
            return child
        child = user32.FindWindowExW(frame, child, "ShellTabWindowClass", None)
    return 0


def _tab_hwnd_of(w) -> int:
    try:
        import pythoncom
        from win32com.shell import shell
        sp = w._oleobj_.QueryInterface(pythoncom.IID_IServiceProvider)
        sid_top = pythoncom.MakeIID("{4C96BE40-915C-11CF-99D3-00AA004AE837}")   # SID_STopLevelBrowser
        browser = sp.QueryService(sid_top, shell.IID_IShellBrowser)
        return int(browser.GetWindow())
    except Exception:
        return 0


def _desktop_selection(focused=False) -> list[str]:
    import pythoncom
    import win32com.client
    sw = win32com.client.Dispatch("{9BA05972-F6A8-11CF-A442-00A0C90A8F39}")   # ShellWindows
    empty = win32com.client.VARIANT(pythoncom.VT_EMPTY, None)
    attempts = (
        lambda: sw.FindWindowSW(empty, empty, 8, win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0), 1),
        lambda: sw.FindWindowSW(empty, empty, 8, 0, 1),
        lambda: sw.FindWindowSW(0, 0, 8, 0, 1),
    )
    for attempt in attempts:
        try:
            desk = attempt()
            if isinstance(desk, tuple):
                desk = desk[0]
            if desk is None:
                continue
            if not hasattr(desk, "Document"):
                desk = win32com.client.Dispatch(desk)
            if focused:
                it = desk.Document.FocusedItem
                return [it.Path] if it is not None else []
            return [it.Path for it in desk.Document.SelectedItems()]
        except Exception as e:
            log(f"desktop selection attempt failed: {e}")
    return []


def explorer_selection(hwnd: int | None = None, focused: bool = False) -> list[str]:
    """Paths selected in an Explorer window (the active tab) or on the desktop.
    hwnd: top-level window to read; defaults to the foreground window.
    focused=True returns the item with the focus rectangle instead (the one just Ctrl-clicked)."""
    if not IS_WIN:
        return []
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        return []
    try:
        pythoncom.CoInitialize()
    except Exception:
        pass
    target = hwnd or foreground_hwnd()
    cls = window_class(target)
    try:
        if cls in ("CabinetWClass", "ExploreWClass"):
            shell = win32com.client.Dispatch("Shell.Application")
            matches = []
            for w in shell.Windows():
                try:
                    if int(w.HWND) == target:
                        matches.append(w)
                except Exception:
                    continue
            if not matches:
                return []
            chosen = matches[0]
            if len(matches) > 1:                       # several tabs in one window
                active = _active_tab_hwnd(target)
                by_tab = [w for w in matches if active and _tab_hwnd_of(w) == active]
                title = window_title(target)
                by_title = [w for w in matches if title and str(w.LocationName) and title.startswith(str(w.LocationName))]
                chosen = (by_tab or by_title or matches)[0]
            if focused:
                it = chosen.Document.FocusedItem
                return [it.Path] if it is not None else []
            return [it.Path for it in chosen.Document.SelectedItems()]
        if cls in ("Progman", "WorkerW"):
            return _desktop_selection(focused)
    except Exception as e:
        log(f"explorer_selection failed ({cls}): {e}")
    return []


def is_elevated() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin()) if IS_WIN else False
    except Exception:
        return False


# ----------------------------------------------------------------------------
# Log file: %LOCALAPPDATA%\ConvertANNY\convertanny.log (kept small)
# ----------------------------------------------------------------------------
def log_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "ConvertANNY"
    return base / "convertanny.log"


def log(msg: str) -> None:
    try:
        import time
        p = log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists() and p.stat().st_size > 512_000:
            p.replace(p.with_suffix(".old.log"))
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except Exception:
        pass


# ----------------------------------------------------------------------------
# Launch command for this app
# ----------------------------------------------------------------------------












# ----------------------------------------------------------------------------
# Start with Windows
# ----------------------------------------------------------------------------






# ----------------------------------------------------------------------------
# Explorer right-click menu + Send To
# ----------------------------------------------------------------------------












SYNTHETIC = _input_poll.SYNTHETIC












# ----------------------------------------------------------------------------
# Shell helpers
# ----------------------------------------------------------------------------
def reveal(path):
    from convertanny_core.shell_actions import reveal as open_location
    return open_location(path,windows=IS_WIN,select_in_explorer=_select_in_explorer,log=log)


def _select_in_explorer(paths: list) -> None:
    """SHOpenFolderAndSelectItems: reliable selection (explorer /select is ignored when Explorer is busy
    or the path has unusual characters) and it reuses an already-open window of that folder."""
    from ctypes import wintypes
    shell32, ole32 = ctypes.windll.shell32, ctypes.windll.ole32
    ole32.CoInitialize(None)
    shell32.ILCreateFromPathW.restype = ctypes.c_void_p
    shell32.ILCreateFromPathW.argtypes = [wintypes.LPCWSTR]
    shell32.ILFree.argtypes = [ctypes.c_void_p]
    shell32.SHOpenFolderAndSelectItems.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p, wintypes.DWORD]
    folder = os.path.dirname(os.path.normpath(paths[0]))
    same = [os.path.normpath(x) for x in paths if os.path.dirname(os.path.normpath(x)) == folder]
    pf = shell32.ILCreateFromPathW(folder)
    items = [shell32.ILCreateFromPathW(x) for x in same]
    items = [i for i in items if i]
    if not pf or not items:
        raise OSError("could not resolve path")
    try:
        arr = (ctypes.c_void_p * len(items))(*items)
        hr = shell32.SHOpenFolderAndSelectItems(pf, len(items), arr, 0)
        if hr < 0:                                   # failed HRESULT
            raise OSError(f"SHOpenFolderAndSelectItems {hr & 0xFFFFFFFF:#x}")
    finally:
        for i in items:
            shell32.ILFree(i)
        shell32.ILFree(pf)


def open_terminal(folder):
    from convertanny_core.shell_actions import open_terminal as open_console
    return open_console(folder,windows=IS_WIN)


def open_with(path):
    from convertanny_core.shell_actions import open_with as show_picker
    return show_picker(path,windows=IS_WIN)


# ----------------------------------------------------------------------------
# Low-level mouse hook — only used to see the scroll wheel during a drag
# (GetAsyncKeyState can't report wheel movement). Runs on its own thread.
# ----------------------------------------------------------------------------


# ----------------------------------------------------------------------------
# Run an Explorer right-click entry (e.g. "Send with Quick Share") on files
# ----------------------------------------------------------------------------
def quick_share_installed():
    from convertanny_core.shell_actions import find_quick_share
    return find_quick_share() if IS_WIN else None


def drop_files_on(target, paths) -> bool:
    """Drop files on `target` (a shortcut, program or folder) exactly as Explorer's drag-and-drop or Send To does."""
    if not IS_WIN or not paths:
        return False
    import pythoncom
    from win32com.shell import shell
    try:
        pythoncom.OleInitialize()
    except Exception:
        pass
    desktop = shell.SHGetDesktopFolder()

    def split(path):
        pidl, _attrs = shell.SHParseDisplayName(str(path), 0)
        parent = pidl[:-1]
        folder = desktop.BindToObject(parent, None, shell.IID_IShellFolder) if parent else desktop
        return folder, pidl[-1:]

    tfolder, tchild = split(target)
    drop = tfolder.GetUIObjectOf(0, [tchild], pythoncom.IID_IDropTarget, 0)[1]
    groups = {}
    for p in paths:
        groups.setdefault(str(Path(p).parent), []).append(Path(p))
    done = False
    for _parent, items in groups.items():
        folder, _c = split(items[0])
        kids = [split(x)[1] for x in items]
        data = folder.GetUIObjectOf(0, kids, pythoncom.IID_IDataObject, 0)[1]
        effect = drop.DragEnter(data, 1, (0, 0), 1)            # left button, copy
        if not effect:
            drop.DragLeave()
            continue
        drop.Drop(data, 1, (0, 0), 1)
        done = True
    log(f"dropped {len(paths)} item(s) on {Path(target).name}: {done}")
    return done


def sendto_entry(*words):
    from convertanny_core.shell_actions import sendto_entry as find_shortcut
    return find_shortcut(words)


def invoke_shell_verb(paths, *names, exact=()) -> bool:
    """Run the right-click entry whose text contains one of `names` (earlier names win) or equals one of `exact`
    on all `paths` (same folder = one action). True if it was found and started."""
    from convertanny_core.shell_verbs import invoke
    return invoke(paths, names, exact, windows=IS_WIN, log=log)


def recycle(path: str) -> None:
    """Move a file or folder to the Recycle Bin (can be restored)."""
    if not IS_WIN:
        os.remove(path)
        return
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]
    op = SHFILEOPSTRUCTW()
    op.wFunc = 3                                           # FO_DELETE
    op.pFrom = os.path.abspath(path) + "\0"
    op.fFlags = 0x0040 | 0x0010 | 0x0004 | 0x0400          # ALLOWUNDO, NOCONFIRMATION, SILENT, NOERRORUI
    r = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if r != 0:
        raise OSError(f"Recycle Bin: error {r}")



def shortcut_target(lnk: str) -> str | None:
    """The program a Windows shortcut (.lnk) points to, or None."""
    from convertanny_core.shell_actions import shortcut_target as resolve_target
    return resolve_target(lnk,windows=IS_WIN)


# Keep the synthetic-click quiet period live for polling code that has used the
# winsys namespace historically.
import types as _types
class _InputAwareModule(_types.ModuleType):
    def __getattribute__(self,name):
        if name == "SYNTH_UNTIL":
            from convertanny_core import input_poll
            return input_poll.SYNTH_UNTIL
        return super().__getattribute__(name)
sys.modules[__name__].__class__ = _InputAwareModule
