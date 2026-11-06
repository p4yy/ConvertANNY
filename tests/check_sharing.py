"""Exercise streaming upload framing and host-selection rules without network access."""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from convertanny_core import sharing
from convertanny_core.model import ConversionError


class Response:
    status = 200

    def read(self):
        return b"https://files.example/test"


class Connection:
    def __init__(self, *_args, **_kwargs):
        self.headers = []
        self.sent = bytearray()
        self.closed = False

    def putrequest(self, *_args):
        pass

    def putheader(self, *values):
        self.headers.append(values)

    def endheaders(self):
        pass

    def send(self, value):
        self.sent.extend(value)

    def getresponse(self):
        return Response()

    def close(self):
        self.closed = True


def check():
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / "tmp") as folder:
        source = Path(folder) / "clean file.txt"
        source.write_bytes(b"payload" * 1000)
        connection = Connection()
        progress = []
        with patch.object(sharing.http.client, "HTTPSConnection", return_value=connection):
            result = sharing._upload("https://upload.example/api", source, "file", {"mode": "test"},
                                     progress.append, lambda: False)
        assert result == "https://files.example/test" and connection.closed
        assert bytes(source.read_bytes()) in connection.sent
        length = int(next(value for key, value in connection.headers if key == "Content-Length"))
        assert length == len(connection.sent)
        assert progress[0] > 0 and progress[-1] == 1.0
        assert all(left <= right for left, right in zip(progress, progress[1:]))

        called = []
        def fake_upload(path, minutes, report, cancelled):
            called.append((path, minutes));report(1.0);return "https://files.example/link"
        with patch.dict(sharing._HOSTS, {"example.test": (fake_upload, 2, 240)}), \
             patch.object(sharing, "_host_refusal", return_value=""):
            link, host = sharing.upload_temporary(source, 60, only="example.test")
        assert (link, host) == ("https://files.example/link", "example.test") and len(called) == 1

        called.clear()
        with patch.dict(sharing._HOSTS, {"short.test": (fake_upload, 2, 30)}), \
             patch.object(sharing, "_host_refusal", return_value=""):
            try:
                sharing.upload_temporary(source, 60, only="short.test")
            except OSError as error:
                assert "internet connection" in str(error)
            else:
                raise AssertionError("A host with a shorter expiry than requested was used")
        assert not called
        try:
            sharing.upload_temporary(source, 60, only="unknown.test")
        except ConversionError:
            pass
        else:
            raise AssertionError("An unknown service was accepted")
    print("Streaming HTTPS framing, byte progress, host routing and expiry rules passed with network mocked")


if __name__ == "__main__":
    check()
