"""Characterize saved-link expiry, de-duplication and file-version identity."""
import json
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import runtime


class Settings:
    def __init__(self, value="[]"):
        self.data = {"share_links": value}

    def value(self, key, default=None):
        return self.data.get(key, default)

    def setValue(self, key, value):
        self.data[key] = value


def check_expiry_filter_and_malformed_store_cleanup():
    store = Settings(json.dumps([{"url": "https://alive", "expires": 200},
                                {"url": "https://old", "expires": 90}, "junk"]))
    saved = runtime.settings
    runtime.settings = lambda: store
    try:
        with patch.object(time, "time", return_value=100):
            assert runtime.share_links() == [{"url": "https://alive", "expires": 200}]
        assert json.loads(store.data["share_links"]) == [{"url": "https://alive", "expires": 200}]
        store.data["share_links"] = "not json"
        assert runtime.share_links() == []
    finally:
        runtime.settings = saved


def check_key_tracks_sorted_path_and_file_version():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        first, second = root / "a.txt", root / "b.txt"
        first.write_text("a", encoding="utf-8")
        second.write_text("bb", encoding="utf-8")
        key = runtime.share_key([second, first])
        assert key == runtime.share_key([first, second])
        first.write_text("longer", encoding="utf-8")
        assert key != runtime.share_key([first, second])


def check_remember_replaces_and_caps_history():
    old = [{"url": f"https://old/{n}", "name": str(n), "expires": 1000, "key": ""} for n in range(21)]
    store = Settings(json.dumps(old))
    saved = runtime.settings
    runtime.settings = lambda: store
    try:
        with patch.object(time, "time", return_value=100):
            runtime.remember_share_link("https://new", "one", 5, "k")
            runtime.remember_share_link("https://new", "two", 10, "k2")
        rows = json.loads(store.data["share_links"])
        assert len(rows) == 20 and rows[0] == {
            "url": "https://new", "name": "two", "expires": 700, "key": "k2"}
        assert sum(row["url"] == "https://new" for row in rows) == 1
    finally:
        runtime.settings = saved


if __name__ == "__main__":
    check_expiry_filter_and_malformed_store_cleanup()
    check_key_tracks_sorted_path_and_file_version()
    check_remember_replaces_and_caps_history()
    print("Saved link expiry, file identity, de-duplication and retention passed")
