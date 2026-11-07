"""Verify the updater uses only an explicitly configured ConvertANNY release channel."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QSettings
import updater


class MemorySettings:
    value_to_return = ""

    def __init__(self, *_args):
        pass

    def value(self, _key, default=""):
        return self.value_to_return if self.value_to_return is not None else default


class Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def run():
    with patch("PySide6.QtCore.QSettings", MemorySettings):
        MemorySettings.value_to_return = ""
        assert updater.configured_repository() == ""
        assert updater.releases_url() == ""
        try:
            updater.latest_release()
        except ValueError as error:
            assert "Preferences" in str(error)
        else:
            raise AssertionError("an unconfigured updater must not contact a repository")

        MemorySettings.value_to_return = "someone/UnrelatedApp"
        assert updater.configured_repository() == ""
        MemorySettings.value_to_return = "someone/ConvertANNY"
        assert updater.configured_repository() == "someone/ConvertANNY"
        assert updater.releases_url() == "https://github.com/someone/ConvertANNY/releases/latest"

        MemorySettings.value_to_return = "p4yy/ConvertANNY"
        assert updater.configured_repository() == "p4yy/ConvertANNY"
        assert updater.releases_url() == "https://github.com/p4yy/ConvertANNY/releases/latest"

        response_data = {"tag_name": "v1.2.3", "assets": [], "body": "notes"}
        with patch.object(updater, "_request", return_value=Response()), \
             patch.object(updater.json, "load", return_value=response_data) as load:
            release = updater.latest_release()
        assert release.version == "1.2.3"
        load.assert_called_once()
    print("Updater repository guard: unconfigured and invalid channels fail closed; configured owner/ConvertANNY resolves.")


if __name__ == "__main__":
    run()
