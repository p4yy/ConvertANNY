"""Release record immutability and GitHub release JSON parsing (network mocked)."""
import dataclasses
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import updater


class _Reply(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *exc): return False


def check():
    rel = updater.Release(version="1.2.3", tag="v1.2.3", page="https://example.invalid/r", notes="n")
    assert (rel.installer_url, rel.installer_name, rel.installer_size, rel.installer_sha256) == (None, None, 0, "")
    try:
        rel.version = "9"
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("Release must be immutable")

    saved_request, saved_repo = updater._request, updater.configured_repository
    try:
        updater.configured_repository = lambda: "owner/repo"
        payload = {"tag_name": "v2.0.1", "html_url": "https://example.invalid/page", "body": "  notes  ",
                   "assets": [{"name": "readme.txt", "browser_download_url": "x"},
                              {"name": "ConvertANNY-Setup-2.0.1.exe", "browser_download_url": "https://example.invalid/s.exe",
                               "size": 1234, "digest": "sha256:ABCDEF"}]}
        updater._request = lambda *a, **k: _Reply(json.dumps(payload).encode())
        got = updater.latest_release()
        assert (got.version, got.tag, got.page, got.notes) == ("2.0.1", "v2.0.1", "https://example.invalid/page", "notes")
        assert (got.installer_url, got.installer_name, got.installer_size, got.installer_sha256) == \
               ("https://example.invalid/s.exe", "ConvertANNY-Setup-2.0.1.exe", 1234, "abcdef")
        bare = {"tag_name": "3.0", "assets": []}
        updater._request = lambda *a, **k: _Reply(json.dumps(bare).encode())
        got = updater.latest_release()
        assert got.page == "https://github.com/owner/repo/releases/latest" and got.installer_url is None
        assert got.installer_size == 0 and got.installer_sha256 == "" and got.notes == ""
        updater.configured_repository = lambda: ""
        try:
            updater.latest_release()
        except ValueError:
            pass
        else:
            raise AssertionError("missing repository must be rejected")
    finally:
        updater._request, updater.configured_repository = saved_request, saved_repo
    print("Release record and GitHub release parsing passed")


if __name__ == "__main__":
    check()
