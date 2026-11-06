"""Check Windows shell commands without starting Explorer or a terminal."""
import sys,tempfile,shutil
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from convertanny_core import shell_actions


def check():
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'tmp') as root:
        folder=Path(root);file=folder/'file with spaces.txt';file.write_text('test')
        with patch('convertanny_core.shell_actions.subprocess.Popen') as launch:
            shell_actions.reveal(file,windows=True)
            assert launch.call_args.args[0]==['explorer.exe',f'/select,"{file.resolve()}"']
            shell_actions.open_with(file,windows=True)
            assert launch.call_args.args[0][-1]==str(file.resolve())
            shell_actions.open_terminal(folder,windows=True,which=lambda _:None)
            command=launch.call_args.args[0]
            assert command[-2:]==['Set-Location -LiteralPath $args[0]',str(folder.resolve())]
        sendto=folder/'Microsoft'/'Windows'/'SendTo';sendto.mkdir(parents=True)
        shortcut=sendto/'Bluetooth Device.lnk';shortcut.touch()
        assert shell_actions.sendto_entry(('bluetooth',),appdata=str(folder))==shortcut
        assert shell_actions.find_quick_share([str(folder)]) is None
        target=folder/'application.exe';target.touch()
        class Shortcut:
            TargetPath=str(target)
        class Shell:
            def CreateShortcut(self,link):return Shortcut()
        link=folder/'application.lnk';link.touch()
        assert shell_actions.shortcut_target(link,windows=True,shell_factory=Shell)==str(target)
        assert shell_actions.shortcut_target(link,windows=False,shell_factory=Shell) is None
    print('Shell action paths, quoting, terminal, Send To and optional app lookup passed')


if __name__=='__main__':check()
