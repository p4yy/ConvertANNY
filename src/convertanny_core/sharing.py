"""Streaming HTTPS uploads to user-selected temporary file hosts."""
from __future__ import annotations

import http.client
import json
import mimetypes
import ssl
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from .model import ConversionError


BLOCKED_UPLOAD_EXT = frozenset({
    ".exe", ".msi", ".msix", ".appx", ".bat", ".cmd", ".com", ".scr", ".dll", ".sys", ".cpl", ".jar",
    ".ps1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".hta", ".lnk", ".reg", ".apk", ".xapk", ".ipa",
})


def _translate(translate, message):
    try:
        return translate(message)
    except Exception:
        return message


def _upload(endpoint, source, field, values, progress, cancelled, timeout=180):
    source = Path(source)
    if not source.is_file():
        raise ConversionError(f"File not found: {source}")
    parsed = urlsplit(endpoint)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Temporary upload endpoints must use HTTPS")
    boundary = "----ConvertANNY" + uuid4().hex
    prefix = bytearray()
    for name, value in values.items():
        prefix.extend((f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
                       f"{value}\r\n").encode("utf-8"))
    media_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
    safe_name = quote(source.name, safe="")
    prefix.extend((f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{safe_name}\"\r\n"
                   f"Content-Type: {media_type}\r\n\r\n").encode("utf-8"))
    suffix = f"\r\n--{boundary}--\r\n".encode("ascii")
    total = len(prefix) + source.stat().st_size + len(suffix)
    connection = http.client.HTTPSConnection(parsed.hostname, parsed.port or 443, timeout=timeout,
                                               context=ssl.create_default_context())
    route = parsed.path or "/"
    if parsed.query:
        route += "?" + parsed.query
    done = 0
    try:
        connection.putrequest("POST", route)
        connection.putheader("User-Agent", "ConvertANNY/0.1 (Windows)")
        connection.putheader("Accept", "*/*")
        connection.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
        connection.putheader("Content-Length", str(total))
        connection.endheaders()

        def send(chunk):
            nonlocal done
            if cancelled():
                raise OSError("cancelled")
            connection.send(chunk)
            done += len(chunk)
            progress(done / max(1, total))

        send(prefix)
        with source.open("rb") as stream:
            while True:
                if cancelled():
                    raise OSError("cancelled")
                chunk = stream.read(256 * 1024)
                if not chunk:
                    break
                send(chunk)
        send(suffix)
        response = connection.getresponse()
        body = response.read().decode("utf-8", "replace").strip()
        if response.status < 200 or response.status >= 300:
            raise OSError(f"HTTP {response.status}: {body[:160]}")
        progress(1.0)
        return body
    finally:
        connection.close()


def _litterbox(path, minutes, progress, cancelled):
    hours = min((value for value in (1, 12, 24, 72) if value * 60 >= minutes), default=72)
    result = _upload("https://litterbox.catbox.moe/resources/internals/api.php", path, "fileToUpload",
                     {"reqtype": "fileupload", "time": f"{hours}h"}, progress, cancelled)
    if not result.startswith("https://"):
        raise OSError(result[:120])
    return result


def _zero_x_zero(path, minutes, progress, cancelled):
    hours = max(1, -(-int(minutes) // 60))
    result = _upload("https://0x0.st", path, "file", {"expires": str(hours)}, progress, cancelled)
    if not result.startswith("https://"):
        raise OSError(result[:120])
    return result


def _tmpfiles(path, minutes, progress, cancelled):
    result = json.loads(_upload("https://tmpfiles.org/api/v1/upload", path, "file",
                                {"expire": str(min(48 * 60, int(minutes)) * 60)}, progress, cancelled))
    url = str(result["data"]["url"]).replace("http://", "https://", 1)
    return url.replace("tmpfiles.org/", "tmpfiles.org/dl/", 1)


def _uguu(path, minutes, progress, cancelled):
    result = json.loads(_upload("https://uguu.se/upload", path, "files[]", {}, progress, cancelled))
    return str(result["files"][0]["url"])


_HOSTS = {
    "litterbox.catbox.moe": (_litterbox, 1000, 72 * 60),
    "0x0.st": (_zero_x_zero, 512, 365 * 24 * 60),
    "uguu.se": (_uguu, 128, 3 * 60),
    "tmpfiles.org": (_tmpfiles, 100, 48 * 60),
}
AUTO_HOSTS = ("litterbox.catbox.moe", "0x0.st", "uguu.se")
HOST_CHOICES = (
    ("auto", "Automatic (tries each in turn)", [60, 12 * 60, 24 * 60, 72 * 60]),
    ("litterbox.catbox.moe", "Litterbox — up to 1 GB", [60, 12 * 60, 24 * 60, 72 * 60]),
    ("0x0.st", "0x0.st — up to 512 MB", [60, 12 * 60, 24 * 60, 72 * 60]),
    ("uguu.se", "uguu.se — up to 128 MB", [3 * 60]),
    ("tmpfiles.org", "tmpfiles.org — up to 100 MB (ads)", [5, 15, 30, 60, 12 * 60, 24 * 60, 48 * 60]),
)


def _failure_summary(error, translate):
    message = str(error).casefold()
    rules = (("refuses connections from your network", ("refuses this connection", "403")),
             ("the upload was cut off partway", ("eof occurred", "reset", "timed out")),
             ("refused this kind of file", ("415", "unsupported media")),
             ("the file is too big for it", ("413", "too large")),
             ("couldn't be reached", ("can't be reached", "getaddrinfo", "urlopen error")))
    return _translate(translate, next((label for label, needles in rules if any(word in message for word in needles)), "didn't work"))


def _host_refusal(host):
    request = Request(f"https://{host}/", headers={"User-Agent": "ConvertANNY/0.1 (Windows)"})
    try:
        with urlopen(request, timeout=8) as response:
            response.read(2048)
        return ""
    except HTTPError as error:
        return f"refuses this connection (HTTP {error.code})" if error.code in (401, 403, 451) else ""
    except URLError as error:
        return f"can't be reached ({type(error.reason).__name__}: {error.reason})"
    except Exception as error:
        return f"can't be reached ({type(error).__name__}: {error})"


def upload_temporary(source, minutes, progress=lambda _value: None, cancelled=lambda: False, only=None,
                     *, translate=lambda text: text, log=lambda _message: None):
    source = Path(source)
    size_mb = source.stat().st_size / (1024 * 1024)
    if size_mb > 1000:
        raise OSError(_translate(translate, "Too big for an internet link (the limit is 1 GB)."))
    order = [only] if only and only != "auto" else list(AUTO_HOSTS)
    failures = []
    for name in order:
        if name not in _HOSTS:
            raise ConversionError(f"Unknown temporary upload service: {name}")
        upload, limit, maximum_age = _HOSTS[name]
        if size_mb > limit or maximum_age < minutes:
            failures.append(f"{name}: too large ({size_mb:.0f} MB, limit {limit} MB)" if size_mb > limit
                            else f"{name}: keeps files only {maximum_age // 60} h")
            continue
        refusal = _host_refusal(name)
        if refusal:
            failures.append(f"{name}: {refusal}")
            continue
        for attempt in (1, 2):
            if cancelled():
                raise OSError("cancelled")
            sent = [0.0]
            started = time.monotonic()

            def update(fraction):
                sent[0] = fraction
                progress(fraction)

            try:
                progress(0.0)
                link = upload(source, minutes, update, cancelled)
                log(f"temporary upload: {name} ok ({size_mb:.1f} MB, {minutes} min)")
                return link, name
            except Exception as error:
                if cancelled():
                    raise
                failures.append(f"{name}#{attempt}: {type(error).__name__}: {error} "
                                f"(at {int(sent[0] * 100)}% after {time.monotonic()-started:.0f} s)")
                if not any(key in str(error).casefold() for key in ("eof occurred", "timed out", "reset")):
                    break
    log(f"temporary upload failed ({size_mb:.1f} MB, {minutes} min): " + " | ".join(failures))
    recent = {}
    for failure in failures:
        recent[failure.split(":", 1)[0].split("#")[0]] = failure
    messages = [f"{host}: {_failure_summary(error, translate)}" for host, error in recent.items()
                if "keeps files only" not in error]
    if messages:
        raise OSError(_translate(translate, "Couldn't upload.") + "\n" + "\n".join("• " + item for item in messages)
                      + "\n" + _translate(translate, "Pick another service in the list, or use Quick Share."))
    raise OSError(_translate(translate, "Couldn't upload. Check the internet connection and try again."))
