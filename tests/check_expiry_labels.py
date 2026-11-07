"""Share expiry labels retain the existing minute/hour rounding rules."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from convertanny_core.expiry import expiry_label, minutes_remaining


def tr(message, **values):
    return message.format(**values)


def main():
    assert minutes_remaining(100, now=100) == 1
    assert minutes_remaining(159, now=100) == 1
    assert minutes_remaining(160, now=100) == 1
    assert minutes_remaining(3599, now=0) == 59
    assert minutes_remaining(3600, now=0) == 60
    assert expiry_label(159, tr, now=100) == '1 min left'
    assert expiry_label(3600, tr, now=0) == '1 h 0 min left'
    assert expiry_label(7260, tr, now=0) == '2 h 1 min left'
    print('Share expiry labels passed')


if __name__ == '__main__': main()
