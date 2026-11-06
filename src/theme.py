"""ConvertANNY color roles shared by native widgets and painted surfaces."""
from __future__ import annotations

import ctypes
import os
from string import Template

DARK = dict(bg="#101010", surface="#181818", border="#303030", button="#242424", hover="#303030",
            text="#f5f5f7", dim="#a4a4ad", faint="#85858e", side="#141414", canvas="#101010",
            check_a="#2d2d2d", check_b="#202020", accent="#2563eb", accent2="#3b82f6", on_accent="#ffffff",
            danger="#ff6268", ok="#4bd899", link="#73a4ff")
LIGHT = dict(bg="#f5f7f3", surface="#ffffff", border="#dce4df", button="#edf2ee", hover="#e0ebe4",
             text="#16241d", dim="#64786c", faint="#7b8b81", side="#edf2ee", canvas="#e8eee9",
             check_a="#d0d8d2", check_b="#f2f5f2", accent="#2563eb", accent2="#3b82f6", on_accent="#ffffff",
             danger="#c6283a", ok="#16804c", link="#1d4ed8")
DARK_RGBA = dict(panel=(20,20,20,252), ring=(28,28,28,255), ring_hover=(42,42,42,255),
                 wedge=(255,255,255,10), line=(255,255,255,35), shadow=(0,0,0,90),
                 grip=(255,255,255,32), close=(0,0,0,160), busy_track=(255,255,255,45))
LIGHT_RGBA = dict(panel=(245,247,243,252), ring=(255,255,255,255), ring_hover=(224,235,228,255),
                  wedge=(0,0,0,9), line=(25,125,104,45), shadow=(0,0,0,55),
                  grip=(0,0,0,24), close=(0,0,0,95), busy_track=(0,0,0,35))
NAMES = [("system","System"),("light","Light"),("dark","Dark"),("contrast","High contrast")]
# Retain saved theme identifiers from existing preferences.
_VARIANTS = {"midnight":("dark",218), "ocean":("dark",174), "forest":("dark",130),
             "grape":("dark",275), "rose":("light",342), "sand":("light",37)}
_requested_mode = "system"


def set_mode(value: str | None):
    global _requested_mode
    candidate = str(value or "system").lower()
    _requested_mode = candidate if candidate in {"system","light","dark","contrast",*_VARIANTS} else "system"


def mode() -> str:
    return _requested_mode


def windows_high_contrast() -> bool:
    if os.name != "nt":
        return False
    class HighContrast(ctypes.Structure):
        _fields_ = [("size",ctypes.c_uint32),("flags",ctypes.c_uint32),("scheme",ctypes.c_wchar_p)]
    state = HighContrast()
    state.size = ctypes.sizeof(state)
    try:
        success = ctypes.windll.user32.SystemParametersInfoW(0x42,state.size,ctypes.byref(state),0)
        return bool(success and state.flags & 1)
    except (OSError,AttributeError):
        return False


def is_contrast() -> bool:
    return mode() == "contrast" or (mode() == "system" and windows_high_contrast())


def is_dark() -> bool:
    selected = mode()
    if selected in _VARIANTS:
        selected = _VARIANTS[selected][0]
    if selected != "system":
        return selected != "light"
    if windows_high_contrast():
        return True
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
                value,_ = winreg.QueryValueEx(key,"AppsUseLightTheme")
                return not bool(value)
        except OSError:
            pass
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    application = QGuiApplication.instance()
    return application is None or application.styleHints().colorScheme() != Qt.ColorScheme.Light


def pal() -> dict:
    palette = dict(DARK if is_dark() else LIGHT)
    if is_contrast():
        for key in palette:
            palette[key] = "#ffffff" if key in {"text","dim","faint","border","link"} else "#000000"
        palette.update(accent="#2563eb",accent2="#3b82f6",on_accent="#ffffff",ok="#49ff96",danger="#ff7474")
    elif mode() in _VARIANTS:
        from PySide6.QtGui import QColor
        base,hue = _VARIANTS[mode()]
        for role,lightness in (("bg",.08),("surface",.12),("side",.10),("button",.18),("hover",.23),("border",.25)):
            palette[role] = QColor.fromHslF(hue/360,.18,lightness if base=="dark" else 1-lightness*.6).name()
        palette["accent"] = QColor.fromHslF(hue/360,.74,.56 if base=="dark" else .43).name()
        palette["accent2"] = QColor.fromHslF(hue/360,.74,.65 if base=="dark" else .52).name()
        palette["link"] = palette["accent2"]
    return palette


def hexc(name: str) -> str:
    palette = pal()
    if name not in palette:
        raise KeyError(f"Unknown ConvertANNY color role: {name}")
    return palette[name]


def color(name: str):
    from PySide6.QtGui import QColor
    translucent = DARK_RGBA if is_dark() else LIGHT_RGBA
    if name not in translucent:
        return QColor(hexc(name))
    if is_contrast():
        if name in {"line","grip","busy_track"}:
            return QColor("white")
        return QColor(0,0,0,0 if name in {"shadow","wedge"} else 255)
    if mode() in _VARIANTS and name in {"panel","ring","ring_hover"}:
        role = {"panel":"bg","ring":"surface","ring_hover":"hover"}[name]
        result = QColor(hexc(role));result.setAlpha(translucent[name][3]);return result
    return QColor(*translucent[name])


def sheet(template: str) -> str:
    return Template(str(template)).safe_substitute(pal())
