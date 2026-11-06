"""Phone-share URL dispatch contract."""
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from convertanny_core.phone_routes import resolve_request_path


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        file = root / 'a b.txt'; file.write_text('x')
        folder = root / 'Folder'; folder.mkdir()
        assert resolve_request_path('/abc/', 'abc', [file, folder]) == ('page', None)
        assert resolve_request_path('/abc/f/0', 'abc', [file, folder]) == ('file', 0)
        assert resolve_request_path('/abc/f/1', 'abc', [file, folder]) == ('zip', 1)
        assert resolve_request_path('/abc/all.zip', 'abc', [file, folder]) == ('archive', None)
        assert resolve_request_path('/wrong/', 'abc', [file]) == ('not-found', None)
        assert resolve_request_path('/abcNO/', 'abc', [file]) == ('not-found', None)
        assert resolve_request_path('/abc/f/nope', 'abc', [file]) == ('not-found', None)
        assert resolve_request_path('/abc/f/4', 'abc', [file]) == ('not-found', None)
        assert resolve_request_path('/abc/f%2F0', 'abc', [file]) == ('file', 0)
        assert resolve_request_path('/abc/', 'abc', [file]) == ('file', 0)
    print('Phone-share routes passed')


if __name__ == '__main__': main()
