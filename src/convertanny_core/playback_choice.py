"""Select a playable stream from extractor metadata.

ConvertANNY's link player accepts yt-dlp's stream records at this boundary, then
uses a compact playback descriptor independent of the extractor's data model.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
import re
from typing import Any


_CLIENT_PARAMETER = re.compile(r"[/?&]c[/=]([A-Z0-9_]+)")


def player_from_url(url: str | None) -> str:
    """Read the player identifier yt-dlp embeds in a stream URL, if present."""
    match = _CLIENT_PARAMETER.search(url or "")
    return match.group(1) if match else ""


def choose_playback_format(
    info: Mapping[str, Any], *, max_height: int = 1080, is_live: bool = False,
    client_for_url: Callable[[str], str] | None = None,
    unavailable_live_clients: Iterable[str] = (),
    live_client_rank: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Return the best direct or segmented stream, preserving required request headers."""
    records = [row for row in info.get("formats", ()) or ()
               if isinstance(row, Mapping) and row.get("url")
               and row.get("protocol") != "mhtml"]

    def video(row: Mapping[str, Any]) -> bool:
        return row.get("vcodec") not in (None, "none")

    def audio(row: Mapping[str, Any]) -> bool:
        return row.get("acodec") not in (None, "none")

    def height(row: Mapping[str, Any]) -> int:
        try:
            return max(0, int(row.get("height") or 0))
        except (TypeError, ValueError):
            return 0

    def web_file(row: Mapping[str, Any]) -> bool:
        return row.get("protocol") in ("https", "http")

    def segmented(row: Mapping[str, Any]) -> bool:
        return str(row.get("protocol") or "").startswith("m3u8")

    def rank(row: Mapping[str, Any]) -> tuple[int, float]:
        try:
            bitrate = float(row.get("tbr") or 0)
        except (TypeError, ValueError):
            bitrate = 0.0
        return height(row), bitrate

    def best(rows: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | None:
        choices = list(rows)
        if not choices:
            return None
        within_limit = [row for row in choices if height(row) <= max_height]
        return max(within_limit, key=rank) if within_limit else min(choices, key=rank)

    def descriptor(row: Mapping[str, Any], *, with_size: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "url": row["url"], "headers": row.get("http_headers") or {}, "height": height(row)
        }
        if with_size:
            result["size"] = row.get("filesize")
        return result

    muxed = [row for row in records if video(row) and audio(row)]
    selected: dict[str, Any] | None = None

    if is_live:
        streams = [row for row in muxed if segmented(row)]
        blocked = set(unavailable_live_clients)
        if client_for_url:
            working = [row for row in streams if client_for_url(str(row["url"])) not in blocked]
        else:
            working = streams
        priority = live_client_rank or {}
        if working:
            preferred = min(priority.get((client_for_url(str(row["url"])) if client_for_url else "").upper(), 3)
                            for row in working)
            working = [row for row in working
                       if priority.get((client_for_url(str(row["url"])) if client_for_url else "").upper(), 3)
                       == preferred]
        row = best(working) or best(muxed)
        if row:
            selected = descriptor(row)
    else:
        avc_mp4 = [row for row in records if video(row) and not audio(row) and web_file(row)
                    and str(row.get("vcodec") or "").startswith(("avc", "h264"))
                    and row.get("ext") == "mp4"]
        audio_only = [row for row in records if audio(row) and not video(row) and web_file(row)
                      and row.get("ext") in ("m4a", "mp4")]
        picture = best(avc_mp4)
        sound = max(audio_only, key=lambda row: _bitrate(row, "abr", "tbr"), default=None)
        combined = best(row for row in muxed if web_file(row))

        if picture and sound and (combined is None or height(picture) > height(combined)):
            selected = descriptor(picture, with_size=True)
            selected["audio"] = sound["url"]
            selected["audio_size"] = sound.get("filesize")
        elif combined:
            selected = descriptor(combined, with_size=True)
        else:
            row = best(row for row in muxed if segmented(row)) or best(muxed)
            if row:
                selected = descriptor(row)
            elif records and all(audio(row) and not video(row) for row in records):
                row = max(records, key=lambda item: _bitrate(item, "abr", "tbr"))
                selected = descriptor(row, with_size=True)

    if selected is None and info.get("url"):
        selected = {"url": info["url"], "headers": info.get("http_headers") or {},
                    "height": height(info)}
    return selected or {}


def _bitrate(row: Mapping[str, Any], *fields: str) -> float:
    for field in fields:
        try:
            value = float(row.get(field) or 0)
        except (TypeError, ValueError):
            continue
        if value:
            return value
    return 0.0
