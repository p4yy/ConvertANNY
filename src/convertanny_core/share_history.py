"""Persistence rules for expiring links created by ConvertANNY's sharing flows."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path


def live_links(store, *, now: float | None = None) -> list[dict]:
    """Load active links and compact expired or malformed entries from the settings store."""
    try:
        payload = store.value("share_links", "[]") or "[]"
        entries = json.loads(payload)
    except (TypeError, ValueError):
        entries = []
    current = time.time() if now is None else now
    valid = [entry for entry in entries if isinstance(entry, dict) and entry.get("expires", 0) > current]
    if len(valid) != len(entries):
        store.setValue("share_links", json.dumps(valid, ensure_ascii=False))
    return valid


def file_set_key(paths) -> str:
    """Identify a shared file set, including size and modification time for stale-link checks."""
    records = []
    for raw in sorted(os.path.normcase(os.path.abspath(str(item))) for item in paths):
        try:
            stat = os.stat(raw)
            records.append(f"{raw}|{stat.st_size}|{int(stat.st_mtime)}")
        except OSError:
            records.append(raw)
    return "\n".join(records)


def remember(store, url: str, name: str, minutes: float, key: str = "", *, now: float | None = None) -> None:
    """Move a link to the front of the capped history, renewing its expiry and file-set key."""
    current = time.time() if now is None else now
    entries = [item for item in live_links(store, now=current) if item["url"] != url]
    entries.insert(0, {"url": url, "name": name, "expires": current + minutes * 60, "key": key})
    store.setValue("share_links", json.dumps(entries[:20], ensure_ascii=False))
