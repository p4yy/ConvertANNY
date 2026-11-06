"""ConvertANNY per-user shell registration and launch commands."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PRODUCT = "ConvertANNY"
STARTUP_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
FILE_MENUS = (r"Software\Classes\*\shell\ConvertANNY", r"Software\Classes\Directory\shell\ConvertANNY")
BACKGROUND_MENU = r"Software\Classes\Directory\Background\shell\ConvertANNY"


def app_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable]
    interpreter = Path(sys.executable)
    windowed = interpreter.with_name("pythonw.exe")
    entry = Path(__file__).resolve().parents[1] / "convertanny.py"
    return [str(windowed if windowed.is_file() else interpreter), str(entry)]


def icon_path() -> str:
    if getattr(sys, "frozen", False):
        return sys.executable + ",0"
    return str(Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])) / "assets" / "convertanny.ico")


def _command(arguments=()):
    return subprocess.list2cmdline([*app_command(), *arguments])


def _registry_values(path, values):
    import winreg
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_WRITE) as key:
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(value))


def _remove_key(path):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
            children = []
            while True:
                try:
                    children.append(winreg.EnumKey(key, len(children)))
                except OSError:
                    break
        for child in children:
            _remove_key(path + "\\" + child)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
    except FileNotFoundError:
        pass


def _has_key(path):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path):
            return True
    except OSError:
        return False


def set_startup(enabled: bool):
    if os.name != "nt":
        return
    import winreg
    if enabled:
        _registry_values(STARTUP_KEY, {PRODUCT: _command(["--tray"])})
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, PRODUCT)
        except FileNotFoundError:
            pass


def startup_enabled() -> bool:
    if os.name != "nt":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY) as key:
            return bool(winreg.QueryValueEx(key, PRODUCT)[0])
    except OSError:
        return False


def set_context_menu(enabled: bool, paste_label="Save clipboard image here", link_label="Paste link to Float",
                     float_label="Open Float", sendto=None, qr_label="Read QR code on screen"):
    if os.name != "nt":
        return
    if enabled:
        for path in FILE_MENUS:
            _registry_values(path, {"MUIVerb": PRODUCT, "Icon": icon_path(), "MultiSelectModel": "Player"})
            # Keep Explorer's file placeholder quoted even when its literal text has no spaces.
            _registry_values(path + r"\command", {"": _command(["--open"]) + ' "%1"'})
        _remove_key(BACKGROUND_MENU)
        _registry_values(BACKGROUND_MENU, {"MUIVerb": PRODUCT, "Icon": icon_path(), "SubCommands": ""})
        actions = (("paste", paste_label, "--paste-here", True), ("zlink", link_label, "--play-link", False),
                   ("zyqr", qr_label, "--read-qr", False), ("zzfloat", float_label, "--open-float", False))
        for identifier, label, flag, directory in actions:
            action = BACKGROUND_MENU + "\\shell\\" + identifier
            _registry_values(action, {"MUIVerb": label, "Icon": icon_path()})
            command = _command([flag]) + (' "%V"' if directory else "")
            _registry_values(action + r"\command", {"": command})
    else:
        for path in (*FILE_MENUS, BACKGROUND_MENU):
            _remove_key(path)
    if sendto is not None:
        set_sendto(bool(sendto))
    try:
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
    except (OSError, AttributeError):
        pass


def context_menu_enabled() -> bool:
    return os.name == "nt" and all(_has_key(path + r"\command") for path in FILE_MENUS)


def _sendto_folder():
    return Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "Microsoft" / "Windows" / "SendTo"


def sendto_enabled() -> bool:
    return (_sendto_folder() / "Send to Phone using ConvertANNY.lnk").is_file()


def set_sendto(enabled: bool):
    if os.name != "nt":
        return
    folder = _sendto_folder()
    shortcuts = (("ConvertANNY.lnk", (), "Open selected files in the conversion orbit"),
                 ("Send to Phone using ConvertANNY.lnk", ("--send-phone",), "Send selected files to your phone"))
    for name, arguments, description in shortcuts:
        destination = folder / name
        if not enabled:
            destination.unlink(missing_ok=True)
            continue
        folder.mkdir(parents=True, exist_ok=True)
        import win32com.client
        command = app_command()
        shortcut = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(destination))
        shortcut.TargetPath = command[0]
        shortcut.Arguments = subprocess.list2cmdline([*command[1:], *arguments])
        shortcut.IconLocation = icon_path()
        shortcut.Description = description
        shortcut.WorkingDirectory = str(Path(command[0]).parent)
        shortcut.Save()


def cli_command_file() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "Microsoft" / "WindowsApps" / "convertanny.cmd"


def ensure_cli_command():
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return
    path = cli_command_file()
    executable = sys.executable.replace("%", "%%")
    content = f'@echo off\nstart "" /wait "{executable}" --cli %*\nexit /b %errorlevel%\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file() or path.read_text(encoding="utf-8") != content:
        path.write_text(content, encoding="utf-8")


def open_cli_window():
    ensure_cli_command()
    home = Path.home()
    directory = home / "Downloads" if (home / "Downloads").is_dir() else home
    subprocess.Popen([os.environ.get("COMSPEC", "cmd.exe"), "/k", "convertanny help"],
                     cwd=directory, creationflags=0x00000010 if os.name == "nt" else 0)
