"""Exercise the local phone-share HTTP transport over real loopback sockets."""
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from convertanny_core.phone_server import PhoneFileServer


def request(url):
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read()


def check():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        file = root / "résumé & notes.txt"
        file.write_bytes(b"phone transfer payload")
        folder = root / "Folder"
        folder.mkdir()
        (folder / "nested.txt").write_text("inside", encoding="utf-8")
        requests, downloads = [], []
        server = PhoneFileServer(
            [file, folder], "token-123", host="127.0.0.1", human_size=lambda _: "22 B",
            on_request=lambda address, path: requests.append((address, path)),
            on_download=downloads.append,
        )
        base = f"http://127.0.0.1:{server.port}/token-123"
        try:
            status, headers, page = request(base + "/")
            assert status == 200 and headers.get_content_type() == "text/html"
            assert b"r\xc3\xa9sum\xc3\xa9 &amp; notes.txt" in page and b"Download all (ZIP)" in page

            status, headers, payload = request(base + "/f/0")
            assert status == 200 and payload == b"phone transfer payload"
            assert headers.get_content_type() == "text/plain"
            assert "r%C3%A9sum%C3%A9%20%26%20notes.txt" in headers["Content-Disposition"]

            status, headers, payload = request(base + "/f/1")
            assert status == 200 and headers.get_content_type() == "application/zip"
            with zipfile.ZipFile(BytesIO(payload)) as archive:
                assert archive.namelist() == ["Folder/nested.txt"]
                assert archive.read("Folder/nested.txt") == b"inside"

            status, _, payload = request(base + "/all.zip")
            assert status == 200
            with zipfile.ZipFile(BytesIO(payload)) as archive:
                assert "résumé & notes.txt" in archive.namelist()
                assert archive.read("résumé & notes.txt") == b"phone transfer payload"

            status, _, _ = request("http://127.0.0.1:%d/wrong/" % server.port)
            assert status == 404
            assert requests and all(address == "127.0.0.1" for address, _ in requests)
            assert ["résumé & notes.txt", "Folder.zip", "ConvertANNY.zip"] == downloads
        finally:
            server.close()
    print("Phone-share HTTP transport passed listing, UTF-8 download, folder archive, all-file archive, 404 and callback checks")


if __name__ == "__main__":
    check()
