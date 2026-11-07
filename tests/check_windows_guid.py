"""Windows GUID parser must match the native COM memory layout."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import winsys


def main():
    guid = winsys._guid('{BCDE0395-E52F-467C-8E3D-C4579291692E}')
    assert (guid.a, guid.b, guid.c) == (0xBCDE0395, 0xE52F, 0x467C)
    assert bytes(guid.d) == bytes.fromhex('8E3DC4579291692E')
    assert winsys._guid('bcde0395-e52f-467c-8e3d-c4579291692e').a == guid.a
    try:
        winsys._guid('bad guid')
    except ValueError:
        pass
    else:
        raise AssertionError('Malformed GUID must fail')
    print('Windows GUID layout passed')


if __name__ == '__main__': main()
