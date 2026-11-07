"""Local HTTP transport for temporary, token-scoped file sharing."""
from __future__ import annotations

import html
import http.server
import mimetypes
import shutil
import threading
import zipfile
from pathlib import Path
from urllib.parse import quote

from .phone_routes import resolve_request_path


class PhoneFileServer:
    """Serve selected paths until closed, without coupling transport to a Qt window."""

    def __init__(self, paths, token, *, host, human_size, on_request, on_download):
        self.paths = tuple(Path(path) for path in paths)
        self.token = token
        self._human_size = human_size
        self._on_request = on_request
        self._on_download = on_download
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(handler):
                client = handler.client_address[0]
                target = handler.path
                owner._on_request(client, target)
                action, index = resolve_request_path(target, owner.token, owner.paths)
                if action == "not-found":
                    handler.send_error(404)
                elif action == "page":
                    handler._send_listing()
                elif action == "file":
                    handler._send_file(owner.paths[index])
                elif action == "zip":
                    handler._send_archive([owner.paths[index]])
                else:
                    handler._send_archive(owner.paths)

            def _send_listing(handler):
                rows = []
                for index, path in enumerate(owner.paths):
                    suffix = " (ZIP)" if path.is_dir() else ""
                    name = html.escape(path.name)
                    size = html.escape(str(owner._human_size(path)))
                    rows.append(f'<a class="f" href="/{owner.token}/f/{index}">{name}{suffix}'
                                f'<small>{size}</small></a>')
                body = (
                    '<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">'
                    '<title>ConvertANNY</title>'
                    '<style>body{font:16px system-ui;margin:0;padding:18px;background:#1c1c1e;color:#f5f5f7}'
                    '.f{display:block;padding:14px;margin:10px 0;border-radius:12px;background:#2c2c2e;color:#fff;'
                    'text-decoration:none}small{display:block;color:#a1a1a6;margin-top:4px}'
                    '.all{background:#ff8a00;color:#1c1c1e;font-weight:600}</style>'
                    '<h3>ConvertANNY</h3>' + ''.join(rows) +
                    f'<a class="f all" href="/{owner.token}/all.zip">Download all (ZIP)</a>'
                ).encode("utf-8")
                handler.send_response(200)
                handler.send_header("Content-Type", "text/html; charset=utf-8")
                handler.send_header("Content-Length", str(len(body)))
                handler.end_headers()
                handler.wfile.write(body)

            def _send_file(handler, path):
                owner._on_download(path.name)
                handler.send_response(200)
                handler.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
                handler.send_header("Content-Length", str(path.stat().st_size))
                handler.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(path.name))
                handler.end_headers()
                try:
                    with path.open("rb") as source:
                        shutil.copyfileobj(source, handler.wfile)
                except OSError:
                    # A client may close the connection before a large transfer finishes.
                    pass

            def _send_archive(handler, paths):
                name = (paths[0].name if len(paths) == 1 else "ConvertANNY") + ".zip"
                owner._on_download(name)
                handler.send_response(200)
                handler.send_header("Content-Type", "application/zip")
                handler.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(name))
                handler.end_headers()
                try:
                    with zipfile.ZipFile(handler.wfile, "w", zipfile.ZIP_STORED) as archive:
                        for item in paths:
                            members = [item] if item.is_file() else (entry for entry in item.rglob("*") if entry.is_file())
                            for member in members:
                                archive.write(member, str(member.relative_to(item.parent)))
                except OSError:
                    # Treat a disconnected client as a cancelled transfer.
                    pass

            def log_message(handler, *_args):
                return

        self.httpd = http.server.ThreadingHTTPServer((host, 0), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self._thread = threading.Thread(target=self.httpd.serve_forever, name="ConvertANNY-phone-share", daemon=True)
        self._thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._thread.join(timeout=2)
