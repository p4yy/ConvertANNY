"""QR payload interpretation contracts, including Wi-Fi escaping."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import runtime


def main():
    cases = [
        (' https://example.org/path ', ('Link', 'https://example.org/path', [('Website', 'example.org')], 'https://example.org/path')),
        (r'WIFI:S:Office\;Guest;P:a\:b\\c;;', ('Wi-Fi network', 'Office;Guest', [('Network', 'Office;Guest'), ('Password', 'a:b\\c')], None)),
        ('wifi:S:first;S:last;P:;', ('Wi-Fi network', 'last', [('Network', 'last')], None)),
        ('WIFI:P:secret;', ('Wi-Fi network', '', [('Password', 'secret')], None)),
        ('MAILTO:ace@example.org', ('Email', 'ace@example.org', [], 'MAILTO:ace@example.org')),
        ('tel:+441234', ('Phone number', '+441234', [], 'tel:+441234')),
        (' ordinary text ', ('Text', 'ordinary text', [], None)),
        ('', ('Text', '', [], None)),
    ]
    with patch.object(runtime, 'tr', lambda text: text):
        for payload, expected in cases:
            assert runtime._qr_meaning(payload) == expected, payload
    print('QR payload contracts passed')


if __name__ == '__main__':
    main()
