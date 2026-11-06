"""Behavioral contract for link playback stream selection."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from convertanny_core.playback_choice import choose_playback_format


def run():
    records = [
        {"url": "https://media/video-720", "protocol": "https", "ext": "mp4", "height": 720,
         "vcodec": "avc1", "acodec": "none", "filesize": 120},
        {"url": "https://media/video-1080", "protocol": "https", "ext": "mp4", "height": 1080,
         "vcodec": "avc1", "acodec": "none", "filesize": 220},
        {"url": "https://media/audio", "protocol": "https", "ext": "m4a", "height": 0,
         "vcodec": "none", "acodec": "mp4a", "abr": 128, "filesize": 15},
        {"url": "https://media/muxed", "protocol": "https", "ext": "mp4", "height": 720,
         "vcodec": "avc1", "acodec": "mp4a", "filesize": 130},
    ]
    choice = choose_playback_format({"formats": records}, max_height=1080)
    assert choice == {"url": "https://media/video-1080", "audio": "https://media/audio",
                      "headers": {}, "height": 1080, "size": 220, "audio_size": 15}

    capped = choose_playback_format({"formats": records}, max_height=720)
    assert capped["url"] == "https://media/muxed"

    live_records = [
        {"url": "https://x/c=WEB/720.m3u8", "protocol": "m3u8_native", "height": 720,
         "vcodec": "avc1", "acodec": "aac"},
        {"url": "https://x/c=MWEB/480.m3u8", "protocol": "m3u8_native", "height": 480,
         "vcodec": "avc1", "acodec": "aac"},
        {"url": "https://x/c=MWEB/1080.m3u8", "protocol": "m3u8_native", "height": 1080,
         "vcodec": "avc1", "acodec": "aac"},
    ]
    def client(url):
        return "MWEB" if "/c=MWEB/" in url else "WEB"
    live = choose_playback_format({"formats": live_records}, max_height=720, is_live=True,
                                  client_for_url=client, unavailable_live_clients={"WEB"},
                                  live_client_rank={"MWEB": 0, "WEB": 5})
    assert live["url"] == "https://x/c=MWEB/480.m3u8"

    music = {"formats": [{"url": "https://x/low", "protocol": "https", "ext": "m4a", "abr": 96,
                          "vcodec": "none", "acodec": "aac"},
                         {"url": "https://x/high", "protocol": "https", "ext": "m4a", "abr": 256,
                          "vcodec": "none", "acodec": "aac"}]}
    assert choose_playback_format(music)["url"] == "https://x/high"
    assert choose_playback_format({"url": "https://x/direct", "height": "360"}) == {
        "url": "https://x/direct", "headers": {}, "height": 360}
    print("Stream selection behavior passed for adaptive, muxed, live, music and direct links")


if __name__ == "__main__":
    run()
