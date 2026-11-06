"""A cache refresh runs once at a time and can be started again afterward."""
import sys
import threading
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from convertanny_core.background_refresh import SingleFlightRefresh


def main():
    refresh = SingleFlightRefresh()
    entered, release = threading.Event(), threading.Event()
    values = []
    def operation():
        entered.set()
        assert release.wait(2)
        return ['192.168.1.2']
    assert refresh.start(operation, values.append)
    assert entered.wait(1)
    assert not refresh.start(lambda: ['wrong'], values.append)
    release.set()
    deadline = time.monotonic() + 2
    while not values and time.monotonic() < deadline:
        time.sleep(.005)
    assert values == [['192.168.1.2']]
    finished = threading.Event()
    assert refresh.start(lambda: ['10.0.0.2'], lambda value: (values.append(value), finished.set()))
    assert finished.wait(1)
    assert values[-1] == ['10.0.0.2']
    print('Single-flight refresh passed')


if __name__ == '__main__': main()
