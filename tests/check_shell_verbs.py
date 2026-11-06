"""Check verb preference and multi-file grouping without invoking Explorer."""
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from convertanny_core.shell_verbs import invoke


class Verb:
    def __init__(self, label):
        self.Name = label
        self.DoIt = Mock()


class VerbSet:
    def __init__(self, labels):
        self.items = [Verb(label) for label in labels]
        self.Count = len(self.items)

    def Item(self, index):
        return self.items[index]


def check():
    commands = VerbSet(["Bluetooth Device", "Send &&Nearby", "Other"])

    class Namespace:
        def ParseName(self, name):
            return self

        def Verbs(self):
            return commands

        def Items(self):
            return self

        def Filter(self, flags, names):
            assert flags == 0xE0
            assert names == "first.txt;second.txt"

    class Shell:
        def Namespace(self, folder):
            return Namespace()

    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / "tmp") as folder:
        root = Path(folder)
        files = [root / "first.txt", root / "second.txt"]
        assert invoke(files, ("nearby", "bluetooth"), windows=True,
                      shell_factory=Shell, initialize=lambda: None)
        commands.items[1].DoIt.assert_called_once_with()
        assert not invoke(files, windows=False, shell_factory=Shell, initialize=lambda: None)
    print("Context-menu command selection and multi-file grouping passed")


if __name__ == "__main__":
    check()
