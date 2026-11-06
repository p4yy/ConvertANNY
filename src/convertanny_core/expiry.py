"""Small time calculations used by expiring share links."""
import time


def minutes_remaining(expires, *, now=None):
    current = time.time() if now is None else now
    return max(1, int((expires - current) // 60))


def expiry_label(expires, translate, *, now=None):
    minutes = minutes_remaining(expires, now=now)
    if minutes < 60:
        return translate("{n} min left", n=minutes)
    return translate("{h} h {m} min left", h=minutes // 60, m=minutes % 60)
