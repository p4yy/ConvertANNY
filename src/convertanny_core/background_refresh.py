"""Prevent duplicate background refresh workers for small process-wide caches."""
from threading import Lock, Thread


class SingleFlightRefresh:
    def __init__(self):
        self._lock = Lock()
        self._running = False

    def start(self, operation, completed):
        with self._lock:
            if self._running:
                return False
            self._running = True

        def work():
            try:
                completed(operation())
            except Exception:
                pass
            finally:
                with self._lock:
                    self._running = False

        Thread(target=work, daemon=True).start()
        return True
