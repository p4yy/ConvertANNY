"""Characterization checks for web-link playback: stream choice and the yt-dlp resolver.

yt-dlp is replaced by a scripted fake, so these run offline and pin the exact commands issued
(including their order), the retry-after-update behaviour, and the shape of what the float player gets.
"""
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import engine


def F(h=0, v="avc1.64", a="none", proto="https", ext="mp4", url=None, tbr=None, abr=None, size=None, hdr=None):
    d = {"url": url or f"https://cdn/{ext}/{h}/{v}/{a}/{proto}", "height": h, "vcodec": v, "acodec": a,
         "protocol": proto, "ext": ext}
    for key, val in (("tbr", tbr), ("abr", abr), ("filesize", size), ("http_headers", hdr)):
        if val is not None:
            d[key] = val
    return d


HDR = {"User-Agent": "UA", "X-Junk": "1"}
CASES = {
 "vod_split": ({"formats":[F(1080,hdr=HDR,size=100),F(720),F(360),F(0,v="none",a="mp4a",ext="m4a",abr=48,size=5),F(0,v="none",a="mp4a",ext="m4a",abr=128,size=9),F(360,v="avc1",a="mp4a")]},1080,False),
 "vod_split_capped": ({"formats":[F(1080),F(720),F(360),F(0,v="none",a="mp4a",ext="m4a",abr=128),F(360,v="avc1",a="mp4a")]},480,False),
 "vod_split_700": ({"formats":[F(1080),F(720),F(360),F(0,v="none",a="mp4a",ext="m4a",abr=128),F(360,v="avc1",a="mp4a")]},720,False),
 "vod_single_only": ({"formats":[F(480,a="mp4a",size=7),F(720,a="mp4a",size=8),F(720,a="mp4a",tbr=900,url="https://cdn/b")]},1080,False),
 "vod_vp9_ignored": ({"formats":[F(1080,v="vp09",ext="webm"),F(0,v="none",a="opus",ext="webm"),F(360,a="mp4a")]},1080,False),
 "vod_hls_only": ({"formats":[F(720,a="mp4a",proto="m3u8_native"),F(1080,a="mp4a",proto="m3u8")]},1080,False),
 "vod_all_above_cap": ({"formats":[F(1080,a="mp4a"),F(720,a="mp4a")]},360,False),
 "music_only": ({"formats":[F(0,v="none",a="mp4a",ext="m4a",abr=64,size=1),F(0,v="none",a="opus",ext="webm",abr=160,size=2)]},1080,False),
 "url_only": ({"url":"https://cdn/direct.mp4","height":480,"http_headers":{"Referer":"r"}},1080,False),
 "empty": ({},1080,False),
 "junk_formats": ({"formats":[{"height":720},{"url":"https://m","protocol":"mhtml","vcodec":"avc1","acodec":"mp4a"}]},1080,False),
 "live_ranked": ({"formats":[F(720,a="mp4a",proto="m3u8_native",url="https://cdn/live/c/ANDROID_VR/a.m3u8"),F(1080,a="mp4a",proto="m3u8_native",url="https://cdn/live/c/WEB/b.m3u8"),F(480,a="mp4a",proto="m3u8_native",url="https://cdn/live/c/MWEB/c.m3u8"),F(720,a="mp4a",proto="m3u8_native",url="https://cdn/live/c/MWEB/d.m3u8",tbr=2),F(720,a="mp4a",proto="m3u8_native",url="https://cdn/live/c/MWEB/e.m3u8",tbr=9)]},1080,True),
 "live_cap": ({"formats":[F(1080,a="mp4a",proto="m3u8_native",url="https://cdn/c/MWEB/1080"),F(360,a="mp4a",proto="m3u8_native",url="https://cdn/c/MWEB/360")]},480,True),
 "live_bad_client": ({"formats":[F(720,a="mp4a",proto="m3u8_native",url="https://cdn/c/MWEB/m"),F(720,a="mp4a",proto="m3u8_native",url="https://cdn/c/TVHTML5/t")]},1080,True),
 "live_all_bad": ({"formats":[F(720,a="mp4a",proto="m3u8_native",url="https://cdn/c/MWEB/m")]},1080,True),
 "live_non_hls": ({"formats":[F(720,a="mp4a",proto="https",url="https://cdn/plain")]},1080,True),
 "live_unknown_client": ({"formats":[F(720,a="mp4a",proto="m3u8",url="https://cdn/x/one"),F(1080,a="mp4a",proto="m3u8",url="https://cdn/x/two")]},1080,True),
}
BAD={"live_bad_client":{"MWEB"},"live_all_bad":{"MWEB"}}

PICK_GOLDEN = json.loads('''{
 "empty": {},
 "junk_formats": {},
 "live_all_bad": {
  "headers": {},
  "height": 720,
  "url": "https://cdn/c/MWEB/m"
 },
 "live_bad_client": {
  "headers": {},
  "height": 720,
  "url": "https://cdn/c/TVHTML5/t"
 },
 "live_cap": {
  "headers": {},
  "height": 360,
  "url": "https://cdn/c/MWEB/360"
 },
 "live_non_hls": {
  "headers": {},
  "height": 720,
  "url": "https://cdn/plain"
 },
 "live_ranked": {
  "headers": {},
  "height": 720,
  "url": "https://cdn/live/c/MWEB/e.m3u8"
 },
 "live_unknown_client": {
  "headers": {},
  "height": 1080,
  "url": "https://cdn/x/two"
 },
 "music_only": {
  "headers": {},
  "height": 0,
  "size": 2,
  "url": "https://cdn/webm/0/none/opus/https"
 },
 "url_only": {
  "headers": {
   "Referer": "r"
  },
  "height": 480,
  "url": "https://cdn/direct.mp4"
 },
 "vod_all_above_cap": {
  "headers": {},
  "height": 720,
  "size": null,
  "url": "https://cdn/mp4/720/avc1.64/mp4a/https"
 },
 "vod_hls_only": {
  "headers": {},
  "height": 1080,
  "url": "https://cdn/mp4/1080/avc1.64/mp4a/m3u8"
 },
 "vod_single_only": {
  "headers": {},
  "height": 720,
  "size": null,
  "url": "https://cdn/b"
 },
 "vod_split": {
  "audio": "https://cdn/m4a/0/none/mp4a/https",
  "audio_size": 9,
  "headers": {
   "User-Agent": "UA",
   "X-Junk": "1"
  },
  "height": 1080,
  "size": 100,
  "url": "https://cdn/mp4/1080/avc1.64/none/https"
 },
 "vod_split_700": {
  "audio": "https://cdn/m4a/0/none/mp4a/https",
  "audio_size": null,
  "headers": {},
  "height": 720,
  "size": null,
  "url": "https://cdn/mp4/720/avc1.64/none/https"
 },
 "vod_split_capped": {
  "headers": {},
  "height": 360,
  "size": null,
  "url": "https://cdn/mp4/360/avc1/mp4a/https"
 },
 "vod_vp9_ignored": {
  "headers": {},
  "height": 360,
  "size": null,
  "url": "https://cdn/mp4/360/avc1.64/mp4a/https"
 }
}''')


def check_format_choice_matches_recorded_results():
    for name, (info, limit, live) in CASES.items():
        avoid = BAD.get(name, set())
        engine.LIVE_BAD_CLIENTS.clear()
        engine.LIVE_BAD_CLIENTS.update(avoid)
        try:
            via_engine = engine._pick_formats(info, limit, live)
        finally:
            engine.LIVE_BAD_CLIENTS.clear()
        assert via_engine == PICK_GOLDEN[name], (name, via_engine)


def check_player_detection():
    for url, want in (("https://x/c/MWEB/y", "MWEB"), ("https://x/?c=TVHTML5&z", "TVHTML5"),
                      ("https://x/a?x=1&c=WEB", "WEB"), ("", ""), (None, ""), ("https://x/c/web/lower", "")):
        assert engine.yt_client(url) == want, url


class _Proc:
    def __init__(self, out=b"", err=b"", code=0): self.stdout, self.stderr, self.returncode = out, err, code
    def communicate(self, timeout=None): return self.stdout, self.stderr
    def kill(self): pass

def _fmt(h, client, url=None):
    return {"url": url or f"https://v/{client}/{h}.m3u8", "height": h, "vcodec": "avc1", "acodec": "mp4a",
            "protocol": "m3u8_native", "ext": "mp4",
            "http_headers": {"User-Agent": "UA", "Referer": "R", "X-Secret": "s", "Cookie": "c", "Origin": "o"}}

def make_fake(script):
    calls = []
    def respond(cmd):
        calls.append(list(cmd))
        return script(cmd)
    shim = SimpleNamespace(run=lambda cmd, **kw: respond(cmd), Popen=lambda cmd, **kw: respond(cmd),
                           PIPE=-1, DEVNULL=-3, CalledProcessError=Exception, TimeoutExpired=Exception)
    return shim, calls

def clients_of(cmd):
    for a in cmd:
        if isinstance(a, str) and a.startswith("youtube:player_client="): return a.split("=",1)[1]
    return ""

def run_case(script, url, quality=None, bad=(), asset=None):
    shim, calls = make_fake(script)
    saved = (engine.subprocess, engine.model_ready, engine.model_path, engine._link_log, engine._asset)
    logs = []
    engine.subprocess = shim
    engine.model_ready = lambda name: True
    engine.model_path = lambda name: Path("/fake/yt-dlp")
    engine._link_log = logs.append
    engine._asset = asset or (lambda *parts: Path("/missing/convertanny-qjs.exe"))
    engine.LIVE_BAD_CLIENTS.clear(); engine.LIVE_BAD_CLIENTS.update(bad)
    try:
        try:
            res = engine.resolve_link(url, quality)
        except engine.ConversionError as exc:
            res = ("ERR", str(exc))
    finally:
        engine.subprocess, engine.model_ready, engine.model_path, engine._link_log, engine._asset = saved
        engine.LIVE_BAD_CLIENTS.clear()
    return res, calls, logs

def vod_script(cmd):
    info = {"title": "T", "webpage_url": "https://page/x", "formats": [_fmt(1080, "a"), _fmt(480, "b")]}
    return _Proc(json.dumps(info).encode())

def fail_script(cmd):
    if "-U" in cmd: return _Proc(b"up to date\nnow\n", b"", 0)
    return _Proc(b"", b"WARNING: w1\nERROR: [x] Video unavailable\n", 1)

def empty_script(cmd): return _Proc(b"{}", b"", 0)

def live_script(cmd):
    c = clients_of(cmd)
    if "player_client=default" in " ".join(map(str, cmd)) or c.startswith("default"):
        return _Proc(json.dumps({"is_live": True, "title": "L", "formats": [_fmt(720, "base")]}).encode())
    if c == "tv": return _Proc(b"", b"ERROR: nope\n", 1)
    return _Proc(json.dumps({"is_live": True, "formats": [_fmt(720, c, f"https://v/c/{ {'mweb':'MWEB','web_safari':'WEB_SAFARI','android_vr':'ANDROID_VR'}[c] }/p.m3u8")]}).encode())


RESOLVE_GOLDEN = json.loads('''{
 "direct": {
  "calls": [],
  "logs": [],
  "res": {
   "page": "https://h/Path/My%20Clip.MP4?x=1",
   "title": "my clip.mp4",
   "url": "https://h/Path/My%20Clip.MP4?x=1"
  }
 },
 "empty": {
  "calls": [
   [
    "/fake/yt-dlp",
    "-J",
    "--no-playlist",
    "--ignore-no-formats-error",
    "--extractor-args",
    "youtube:player_client=default,web_safari,android_vr,tv,mweb",
    "https://site.example/v"
   ],
   [
    "/fake/yt-dlp",
    "-U"
   ],
   [
    "/fake/yt-dlp",
    "-J",
    "--no-playlist",
    "--ignore-no-formats-error",
    "--extractor-args",
    "youtube:player_client=default,web_safari,android_vr,tv,mweb",
    "https://site.example/v"
   ]
  ],
  "logs": [
   "yt-dlp: Couldn't open this link | ",
   "yt-dlp -U: {}",
   "yt-dlp: Couldn't open this link | "
  ],
  "res": [
   "ERR",
   "Requested format is not available"
  ]
 },
 "fail": {
  "calls": [
   [
    "/fake/yt-dlp",
    "-J",
    "--no-playlist",
    "--ignore-no-formats-error",
    "--extractor-args",
    "youtube:player_client=default,web_safari,android_vr,tv,mweb",
    "https://site.example/v"
   ],
   [
    "/fake/yt-dlp",
    "-U"
   ],
   [
    "/fake/yt-dlp",
    "-J",
    "--no-playlist",
    "--ignore-no-formats-error",
    "--extractor-args",
    "youtube:player_client=default,web_safari,android_vr,tv,mweb",
    "https://site.example/v"
   ]
  ],
  "logs": [
   "yt-dlp: [x] Video unavailable | WARNING: w1",
   "yt-dlp -U: up to date | now",
   "yt-dlp: [x] Video unavailable | WARNING: w1"
  ],
  "res": [
   "ERR",
   "[x] Video unavailable"
  ]
 },
 "live": {
  "calls": [
   [
    "/fake/yt-dlp",
    "-J",
    "--no-playlist",
    "--ignore-no-formats-error",
    "--extractor-args",
    "youtube:player_client=default,web_safari,android_vr,tv,mweb",
    "https://www.youtube.com/watch?v=abc"
   ],
   [
    "/fake/yt-dlp",
    "-J",
    "--no-playlist",
    "--ignore-no-formats-error",
    "--extractor-args",
    "youtube:player_client=mweb",
    "https://www.youtube.com/watch?v=abc"
   ],
   [
    "/fake/yt-dlp",
    "-J",
    "--no-playlist",
    "--ignore-no-formats-error",
    "--extractor-args",
    "youtube:player_client=tv",
    "https://www.youtube.com/watch?v=abc"
   ],
   [
    "/fake/yt-dlp",
    "-J",
    "--no-playlist",
    "--ignore-no-formats-error",
    "--extractor-args",
    "youtube:player_client=web_safari",
    "https://www.youtube.com/watch?v=abc"
   ],
   [
    "/fake/yt-dlp",
    "-J",
    "--no-playlist",
    "--ignore-no-formats-error",
    "--extractor-args",
    "youtube:player_client=android_vr",
    "https://www.youtube.com/watch?v=abc"
   ]
  ],
  "logs": [
   "live player tv: ERROR: nope",
   "link opened in Ns: 720p live via mweb"
  ],
  "res": {
   "alts": [
    {
     "client": "web_safari",
     "headers": {
      "Origin": "o",
      "Referer": "R",
      "User-Agent": "UA"
     },
     "height": 720,
     "url": "https://v/c/WEB_SAFARI/p.m3u8"
    },
    {
     "client": "android_vr",
     "headers": {
      "Origin": "o",
      "Referer": "R",
      "User-Agent": "UA"
     },
     "height": 720,
     "url": "https://v/c/ANDROID_VR/p.m3u8"
    }
   ],
   "client": "mweb",
   "headers": {
    "Cookie": "c",
    "Origin": "o",
    "Referer": "R",
    "User-Agent": "UA"
   },
   "height": 720,
   "live": true,
   "page": "https://www.youtube.com/watch?v=abc",
   "title": "L",
   "url": "https://v/c/MWEB/p.m3u8"
  }
 },
 "live_all_bad": {
  "calls": [
   [
    "/fake/yt-dlp",
    "-J",
    "--no-playlist",
    "--ignore-no-formats-error",
    "--extractor-args",
    "youtube:player_client=default,web_safari,android_vr,tv,mweb",
    "https://youtu.be/abc"
   ]
  ],
  "logs": [
   "link opened in Ns: 720p live via ?"
  ],
  "res": {
   "alts": [],
   "client": "",
   "headers": {
    "Cookie": "c",
    "Origin": "o",
    "Referer": "R",
    "User-Agent": "UA"
   },
   "height": 720,
   "live": true,
   "page": "https://youtu.be/abc",
   "title": "L",
   "url": "https://v/base/720.m3u8"
  }
 },
 "live_bad_lower": {
  "calls": [
   [
    "/fake/yt-dlp",
    "-J",
    "--no-playlist",
    "--ignore-no-formats-error",
    "--extractor-args",
    "youtube:player_client=default,web_safari,android_vr,tv,mweb",
    "https://youtu.be/abc"
   ],
   [
    "/fake/yt-dlp",
    "-J",
    "--no-playlist",
    "--ignore-no-formats-error",
    "--extractor-args",
    "youtube:player_client=tv",
    "https://youtu.be/abc"
   ],
   [
    "/fake/yt-dlp",
    "-J",
    "--no-playlist",
    "--ignore-no-formats-error",
    "--extractor-args",
    "youtube:player_client=web_safari",
    "https://youtu.be/abc"
   ],
   [
    "/fake/yt-dlp",
    "-J",
    "--no-playlist",
    "--ignore-no-formats-error",
    "--extractor-args",
    "youtube:player_client=android_vr",
    "https://youtu.be/abc"
   ]
  ],
  "logs": [
   "live player tv: ERROR: nope",
   "link opened in Ns: 720p live via web_safari"
  ],
  "res": {
   "alts": [
    {
     "client": "android_vr",
     "headers": {
      "Origin": "o",
      "Referer": "R",
      "User-Agent": "UA"
     },
     "height": 720,
     "url": "https://v/c/ANDROID_VR/p.m3u8"
    }
   ],
   "client": "web_safari",
   "headers": {
    "Cookie": "c",
    "Origin": "o",
    "Referer": "R",
    "User-Agent": "UA"
   },
   "height": 720,
   "live": true,
   "page": "https://youtu.be/abc",
   "title": "L",
   "url": "https://v/c/WEB_SAFARI/p.m3u8"
  }
 },
 "live_bad_upper": {
  "calls": [
   [
    "/fake/yt-dlp",
    "-J",
    "--no-playlist",
    "--ignore-no-formats-error",
    "--extractor-args",
    "youtube:player_client=default,web_safari,android_vr,tv,mweb",
    "https://youtu.be/abc"
   ],
   [
    "/fake/yt-dlp",
    "-J",
    "--no-playlist",
    "--ignore-no-formats-error",
    "--extractor-args",
    "youtube:player_client=mweb",
    "https://youtu.be/abc"
   ],
   [
    "/fake/yt-dlp",
    "-J",
    "--no-playlist",
    "--ignore-no-formats-error",
    "--extractor-args",
    "youtube:player_client=tv",
    "https://youtu.be/abc"
   ],
   [
    "/fake/yt-dlp",
    "-J",
    "--no-playlist",
    "--ignore-no-formats-error",
    "--extractor-args",
    "youtube:player_client=web_safari",
    "https://youtu.be/abc"
   ],
   [
    "/fake/yt-dlp",
    "-J",
    "--no-playlist",
    "--ignore-no-formats-error",
    "--extractor-args",
    "youtube:player_client=android_vr",
    "https://youtu.be/abc"
   ]
  ],
  "logs": [
   "live player tv: ERROR: nope",
   "link opened in Ns: 720p live via mweb"
  ],
  "res": {
   "alts": [
    {
     "client": "web_safari",
     "headers": {
      "Origin": "o",
      "Referer": "R",
      "User-Agent": "UA"
     },
     "height": 720,
     "url": "https://v/c/WEB_SAFARI/p.m3u8"
    },
    {
     "client": "android_vr",
     "headers": {
      "Origin": "o",
      "Referer": "R",
      "User-Agent": "UA"
     },
     "height": 720,
     "url": "https://v/c/ANDROID_VR/p.m3u8"
    }
   ],
   "client": "mweb",
   "headers": {
    "Cookie": "c",
    "Origin": "o",
    "Referer": "R",
    "User-Agent": "UA"
   },
   "height": 720,
   "live": true,
   "page": "https://youtu.be/abc",
   "title": "L",
   "url": "https://v/c/MWEB/p.m3u8"
  }
 },
 "live_notyt": {
  "calls": [
   [
    "/fake/yt-dlp",
    "-J",
    "--no-playlist",
    "--ignore-no-formats-error",
    "--extractor-args",
    "youtube:player_client=default,web_safari,android_vr,tv,mweb",
    "https://site.example/live"
   ]
  ],
  "logs": [
   "link opened in Ns: 720p live via ?"
  ],
  "res": {
   "alts": [],
   "client": "",
   "headers": {
    "Cookie": "c",
    "Origin": "o",
    "Referer": "R",
    "User-Agent": "UA"
   },
   "height": 720,
   "live": true,
   "page": "https://site.example/live",
   "title": "L",
   "url": "https://v/base/720.m3u8"
  }
 },
 "vod": {
  "calls": [
   [
    "/fake/yt-dlp",
    "-J",
    "--no-playlist",
    "--ignore-no-formats-error",
    "--extractor-args",
    "youtube:player_client=default,web_safari,android_vr,tv,mweb",
    "https://site.example/watch?v=1"
   ]
  ],
  "logs": [
   "link opened in Ns: 1080p"
  ],
  "res": {
   "client": "",
   "headers": {
    "Cookie": "c",
    "Origin": "o",
    "Referer": "R",
    "User-Agent": "UA"
   },
   "height": 1080,
   "page": "https://page/x",
   "title": "T",
   "url": "https://v/a/1080.m3u8"
  }
 },
 "vod_q480": {
  "calls": [
   [
    "/fake/yt-dlp",
    "-J",
    "--no-playlist",
    "--ignore-no-formats-error",
    "--extractor-args",
    "youtube:player_client=default,web_safari,android_vr,tv,mweb",
    "https://site.example/watch?v=1"
   ]
  ],
  "logs": [
   "link opened in Ns: 480p"
  ],
  "res": {
   "client": "",
   "headers": {
    "Cookie": "c",
    "Origin": "o",
    "Referer": "R",
    "User-Agent": "UA"
   },
   "height": 480,
   "page": "https://page/x",
   "title": "T",
   "url": "https://v/b/480.m3u8"
  }
 },
 "vod_q_empty": {
  "calls": [
   [
    "/fake/yt-dlp",
    "-J",
    "--no-playlist",
    "--ignore-no-formats-error",
    "--extractor-args",
    "youtube:player_client=default,web_safari,android_vr,tv,mweb",
    "https://site.example/watch?v=1"
   ]
  ],
  "logs": [
   "link opened in Ns: 1080p"
  ],
  "res": {
   "client": "",
   "headers": {
    "Cookie": "c",
    "Origin": "o",
    "Referer": "R",
    "User-Agent": "UA"
   },
   "height": 1080,
   "page": "https://page/x",
   "title": "T",
   "url": "https://v/a/1080.m3u8"
  }
 }
}''')

SCENARIOS = {
    "direct": (vod_script, "https://h/Path/My%20Clip.MP4?x=1", None, ()),
    "vod": (vod_script, "https://site.example/watch?v=1", None, ()),
    "vod_q480": (vod_script, "https://site.example/watch?v=1", "480p", ()),
    "vod_q_empty": (vod_script, "https://site.example/watch?v=1", "p", ()),
    "fail": (fail_script, "https://site.example/v", None, ()),
    "empty": (empty_script, "https://site.example/v", None, ()),
    "live": (live_script, "https://www.youtube.com/watch?v=abc", None, ()),
    "live_bad_upper": (live_script, "https://youtu.be/abc", None, ("MWEB",)),
    "live_bad_lower": (live_script, "https://youtu.be/abc", None, ("mweb",)),
    "live_all_bad": (live_script, "https://youtu.be/abc", None, ("mweb", "tv", "web_safari", "android_vr")),
    "live_notyt": (live_script, "https://site.example/live", None, ()),
}


def stable_calls(calls):
    """Ignore the optional bundled QuickJS runtime flag; its presence is checked separately."""
    output = []
    for call in calls:
        normalized = list(call)
        if "--js-runtimes" in normalized:
            index = normalized.index("--js-runtimes")
            del normalized[index:index + 2]
        output.append([arg.replace("\\", "/") if isinstance(arg, str) else arg for arg in normalized])
    return output


def check_resolver_matches_recorded_behaviour():
    for name, (script, url, quality, bad) in SCENARIOS.items():
        res, calls, logs = run_case(script, url, quality, bad)
        want = RESOLVE_GOLDEN[name]
        assert json.loads(json.dumps(res)) == want["res"], (name, res)
        assert stable_calls(calls) == stable_calls(want["calls"]), (name, calls)
        assert [re.sub(r"in [0-9.]+s", "in Ns", line) for line in logs] == want["logs"], (name, logs)


def check_live_player_with_broken_json_is_skipped():
    def script(cmd):
        c = clients_of(cmd)
        if c == "mweb":
            return _Proc(b"{not json", b"", 0)
        return live_script(cmd)
    res, calls, logs = run_case(script, "https://youtu.be/abc")
    assert res["client"] == "web_safari" and [a["client"] for a in res["alts"]] == ["android_vr"], res


def check_js_runtime_flag_only_when_present():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        fake = Path(d) / "qjs.exe"
        fake.write_text("x")
        saved = engine._asset
        try:
            engine._asset = lambda *parts: fake
            _res, calls, _logs = run_case(vod_script, "https://site.example/watch?v=1", asset=lambda *parts: fake)
        finally:
            engine._asset = saved
    assert "--js-runtimes" in calls[0] and f"quickjs:{fake}" in calls[0], calls[0]
    saved = engine._asset
    try:
        _res, calls, _logs = run_case(vod_script, "https://site.example/watch?v=1",
                                      asset=lambda *parts: Path(d) / "missing-qjs.exe")
    finally:
        engine._asset = saved
    assert "--js-runtimes" not in calls[0]


def check_resolver_when_tool_missing():
    saved = engine.model_ready
    try:
        engine.model_ready = lambda name: False
        try:
            engine.resolve_link("https://site.example/v")
        except engine.ConversionError as exc:
            assert str(exc) == "The yt-dlp tool isn't downloaded yet"
        else:
            raise AssertionError("expected an error")
        assert engine.resolve_link("https://a/b.mp3")["title"] == "b.mp3"       # direct links never need it
    finally:
        engine.model_ready = saved


if __name__ == "__main__":
    for fn_name, fn in sorted(globals().items()):
        if fn_name.startswith("check_") and callable(fn):
            fn()
    print("Link format choice and resolver passed")
