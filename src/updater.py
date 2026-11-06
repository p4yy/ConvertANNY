"""ConvertANNY release discovery and verified component downloads."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from uuid import uuid4

USER_AGENT = "ConvertANNY/0.1"
UPDATE_DIR = Path(tempfile.gettempdir()) / "ConvertANNY-update"


def configured_repository() -> str:
    """Return the user's release channel, without assuming a publisher account."""
    from PySide6.QtCore import QSettings
    repository = str(QSettings("ConvertANNY", "ConvertANNY").value("updates/repository", "")).strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/ConvertANNY", repository, re.I):
        return ""
    return repository


def releases_url() -> str:
    repository = configured_repository()
    return f"https://github.com/{repository}/releases/latest" if repository else ""


@dataclass(frozen=True, slots=True)
class Release:
    """A published ConvertANNY release; the installer fields stay empty when no installer is attached."""
    version: str
    tag: str
    page: str
    notes: str = ""
    installer_url: str | None = None
    installer_name: str | None = None
    installer_size: int = 0
    installer_sha256: str = ""


def parse_version(value: str) -> tuple[int, ...]:
    numbers = re.findall(r"[0-9]+", str(value or ""))
    return tuple(map(int, numbers[:4])) or (0,)


def is_newer(remote: str, local: str) -> bool:
    remote_version, local_version = parse_version(remote), parse_version(local)
    width = max(len(remote_version), len(local_version))
    return remote_version + (0,) * (width - len(remote_version)) > local_version + (0,) * (width - len(local_version))


def _request(url, *, accept="application/octet-stream", byte_range=None):
    if not str(url).lower().startswith(("https://", "http://")):
        raise ValueError("A download requires an HTTP or HTTPS address")
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    if byte_range is not None:
        headers["Range"] = f"bytes={byte_range[0]}-{byte_range[1]}"
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30)


def latest_release() -> Release:
    repository = configured_repository()
    if not repository:
        raise ValueError("Set the ConvertANNY release repository in Preferences first")
    endpoint = f"https://api.github.com/repos/{repository}/releases/latest"
    with _request(endpoint, accept="application/vnd.github+json") as response:
        data = json.load(response)
    tag = str(data.get("tag_name") or "")
    assets = [item for item in data.get("assets", []) if re.fullmatch(r"ConvertANNY-Setup(?:-[^/\\]+)?\.exe", str(item.get("name", "")), re.I)]
    asset = assets[0] if assets else {}
    digest = str(asset.get("digest") or "")
    digest = digest.removeprefix("sha256:") if digest.startswith("sha256:") else ""
    return Release(version=tag.lstrip("vV"), tag=tag,
                   page=str(data.get("html_url") or f"https://github.com/{repository}/releases/latest"),
                   notes=str(data.get("body") or "").strip(),
                   installer_url=asset.get("browser_download_url"), installer_name=asset.get("name"),
                   installer_size=int(asset.get("size") or 0), installer_sha256=digest.lower())


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _target(folder, name):
    name = str(name)
    if not name or name in (".", "..") or any(character in name for character in '/\\:\x00'):
        raise ValueError("Invalid download filename")
    return Path(folder or UPDATE_DIR) / name


def cached_installer(name: str, size: int = 0, sha256: str = "", folder: Path | None = None) -> Path | None:
    path = _target(folder, name)
    try:
        if not path.is_file() or (size and path.stat().st_size != size):
            return None
        if sha256 and sha256_of(path).casefold() != sha256.casefold():
            return None
        return path
    except OSError:
        return None


def cleanup(current_version: str):
    if not UPDATE_DIR.is_dir():
        return
    for item in UPDATE_DIR.iterdir():
        match = re.fullmatch(r"ConvertANNY-Setup-(.+)\.exe", item.name, re.I)
        if match and item.is_file() and not is_newer(match.group(1), current_version):
            try:
                item.unlink()
            except OSError:
                pass


def download(url: str, name: str, progress=None, should_stop=lambda: False, parts: int = 8,
             size: int = 0, sha256: str = "", folder: Path | None = None) -> Path:
    """Download into a private partial file; check length and digest before publishing."""
    target = _target(folder, name)
    existing = cached_installer(name, size, sha256, folder)
    if existing:
        if progress:
            progress(existing.stat().st_size, existing.stat().st_size)
        return existing
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.part")
    mutex = Lock()
    completed = 0
    total = int(size or 0)
    def cancelled():
        if should_stop():
            raise InterruptedError("Download cancelled")
    def report(amount):
        nonlocal completed
        with mutex:
            completed += amount
            if progress:
                progress(completed, total)
    try:
        cancelled()
        with _request(url, byte_range=(0, 0)) as probe:
            ranged = probe.status == 206
            content_range = re.fullmatch(r"bytes 0-0/([0-9]+)", probe.headers.get("Content-Range", ""))
            remote_size = int(content_range.group(1)) if ranged and content_range else int(probe.headers.get("Content-Length") or 0)
            if size and remote_size and size != remote_size:
                raise IOError("Download size does not match the release information")
            total = remote_size or total
            final_url = probe.geturl()
            ranged = ranged and bool(content_range) and total >= 4 * 1024 * 1024 and int(parts) > 1
        if ranged:
            count = min(8, max(1, int(parts)))
            step = (total + count - 1) // count
            with temporary.open("wb") as stream:
                stream.truncate(total)
            def fetch(start, end):
                cancelled()
                with _request(final_url, byte_range=(start, end)) as response:
                    expected_range = f"bytes {start}-{end}/{total}"
                    if response.status != 206 or response.headers.get("Content-Range") != expected_range:
                        raise IOError("The server returned an incorrect download range")
                    remaining = end - start + 1
                    with temporary.open("r+b") as stream:
                        stream.seek(start)
                        while remaining:
                            cancelled()
                            chunk = response.read(min(256 * 1024, remaining))
                            if not chunk:
                                raise IOError("Download ended before the file was complete")
                            stream.write(chunk)
                            remaining -= len(chunk)
                            report(len(chunk))
            with ThreadPoolExecutor(max_workers=count) as executor:
                futures = [executor.submit(fetch, start, min(start + step, total) - 1) for start in range(0, total, step)]
                for future in futures:
                    future.result()
        else:
            with _request(final_url) as response, temporary.open("wb") as stream:
                while True:
                    cancelled()
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    stream.write(chunk)
                    report(len(chunk))
        cancelled()
        if total and temporary.stat().st_size != total:
            raise IOError("Download ended before the file was complete")
        if sha256 and sha256_of(temporary).casefold() != sha256.casefold():
            raise IOError("Download checksum does not match")
        os.replace(temporary, target)
        return target
    finally:
        temporary.unlink(missing_ok=True)
