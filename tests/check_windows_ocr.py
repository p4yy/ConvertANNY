"""OCR adapter contract: text, error translation, and scratch cleanup."""
import sys
import tempfile
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import engine
from PIL import Image


def main():
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / 'sample.png'
        Image.new('RGB', (32, 32), 'white').save(source)
        scratch = []

        def response(data, code=0):
            def run(command, **options):
                script = Path(command[command.index('-File') + 1])
                image = Path(command[command.index('-Path') + 1])
                assert script.is_file() and image.is_file()
                assert options['timeout'] == 120
                scratch.append(script.parent)
                return SimpleNamespace(stdout=data, returncode=code)
            return run

        with patch.object(engine, 'IS_WIN', True):
            with patch.object(engine.subprocess, 'run', response('  Hello مرحبا  '.encode())):
                output = engine.image_ocr(source, {})
                assert output.name == 'sample text.txt'
                assert output.read_text(encoding='utf-8') == 'Hello مرحبا\n'
            for data, code, expected in [(b'', 0, 'No text found'), (b'', 1, "isn't available")]:
                with patch.object(engine.subprocess, 'run', response(data, code)):
                    try:
                        engine.image_ocr(source, {})
                    except engine.ConversionError as error:
                        assert expected in str(error)
                    else:
                        raise AssertionError('Expected OCR failure')
        assert all(not path.exists() for path in scratch)
        def timeout(command, **options):
            scratch.append(Path(command[command.index('-File') + 1]).parent)
            raise subprocess.TimeoutExpired(command, options['timeout'])
        with patch.object(engine, 'IS_WIN', True), patch.object(engine.subprocess, 'run', timeout):
            try:
                engine.image_ocr(source, {})
            except subprocess.TimeoutExpired:
                pass
            else:
                raise AssertionError('Expected recognizer timeout')
        assert all(not path.exists() for path in scratch)
        assert sorted(p.name for p in Path(folder).iterdir()) == ['sample text.txt', 'sample.png']
        assert not list(Path(folder).glob('*.part'))
        with patch.object(engine, 'IS_WIN', False):
            try:
                engine.image_ocr(source, {})
            except engine.ConversionError as error:
                assert 'Windows 10 or 11' in str(error)
            else:
                raise AssertionError('Expected unsupported platform error')
    print('OCR contract checks passed (mocked Windows recognizer)')


if __name__ == '__main__':
    main()
