"""Small native shell actions with argument-safe process launching."""
from pathlib import Path
import os
import shutil
import subprocess


def reveal(paths,*,windows,select_in_explorer=None,log=lambda message:None,environment=None):
    values=[Path(value) for value in (paths if isinstance(paths,(list,tuple)) else [paths]) if value]
    if not values:return
    first=values[0]
    if not windows:
        opener=shutil.which('open') if __import__('sys').platform=='darwin' else shutil.which('xdg-open')
        if opener:subprocess.Popen([opener,str(first if first.is_dir() else first.parent)])
        return
    existing=[str(value.resolve()) for value in values if value.exists()]
    try:
        if select_in_explorer and existing:select_in_explorer(existing);return
        if first.exists() and first.is_file():
            subprocess.Popen(['explorer.exe',f'/select,"{first.resolve()}"'])
        else:subprocess.Popen(['explorer.exe',str(first.resolve())])
    except Exception as error:
        log(f'Could not reveal item in Explorer: {error}')


def open_terminal(folder,*,windows,which=shutil.which,environment=None):
    if not windows:return
    directory=str(Path(folder).resolve());terminal=which('wt')
    if terminal:subprocess.Popen([terminal,'-d',directory]);return
    system=os.environ.get('SystemRoot',r'C:\Windows')
    powershell=str(Path(system)/'System32'/'WindowsPowerShell'/'v1.0'/'powershell.exe')
    subprocess.Popen([powershell,'-NoExit','-Command','Set-Location -LiteralPath $args[0]',directory],
                     creationflags=subprocess.CREATE_NEW_CONSOLE)


def open_with(path,*,windows):
    if windows:subprocess.Popen(['rundll32.exe','shell32.dll,OpenAs_RunDLL',str(Path(path).resolve())])


def find_quick_share(roots=None):
    roots=roots if roots is not None else [os.environ.get('ProgramFiles',r'C:\Program Files'),
        os.environ.get('ProgramFiles(x86)',''),os.path.join(os.environ.get('LOCALAPPDATA',''),'Programs')]
    for root in filter(None,roots):
        for relative in ('Google/NearbyShare','Google/QuickShare','Google/Quick Share','Google/Nearby Share'):
            folder=Path(root)/relative
            if not folder.is_dir():continue
            for name in ('nearby_share.exe','quick_share.exe','QuickShare.exe'):
                try:
                    match=next(folder.rglob(name),None)
                    if match:return str(match)
                except OSError:continue
    return None


def sendto_entry(words,*,appdata=None):
    folder=Path(appdata if appdata is not None else os.environ.get('APPDATA',''))/'Microsoft'/'Windows'/'SendTo'
    try:
        terms=tuple(word.casefold() for word in words)
        return next((item for item in folder.iterdir() if any(term in item.name.casefold() for term in terms)),None)
    except OSError:return None


def shortcut_target(link,*,windows,shell_factory=None):
    """Resolve a Windows shortcut's target through Shell Automation."""
    if not windows:return None
    try:
        if shell_factory is None:
            import win32com.client
            shell_factory=lambda:win32com.client.Dispatch('WScript.Shell')
        target=shell_factory().CreateShortcut(str(Path(link).resolve())).TargetPath
        path=Path(target) if target else None
        return str(path) if path and path.is_file() else None
    except Exception:
        return None
