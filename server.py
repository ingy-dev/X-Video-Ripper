"""Web app for downloading videos and GIFs from public X posts."""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ripper import RipError, extract, open_media, safe_filename

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
MAX_BODY = 16_384
WINDOW_SECONDS = 60
MAX_REQUESTS = 30

_lock = threading.Lock()
_hits: dict[str, list[float]] = {}

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "XRipper/1.0"

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/health":
            self._send_json(200, {"ok": True})
            return
        if parsed.path == "/api/rip":
            self._handle_rip(urllib.parse.parse_qs(parsed.query).get("url", [""])[0])
            return
        if parsed.path in ("/api/download", "/api/file"):
            self._handle_file(parsed.query, attachment=parsed.path == "/api/download")
            return
        self._serve_static(parsed.path)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/api/rip":
            self._send_json(404, {"error": "Not found."})
            return
        length = int(self.headers.get("Content-Length") or "0")
        if length < 0 or length > MAX_BODY:
            self._send_json(400, {"error": "That request is too large."})
            return
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send_json(400, {"error": "Paste a link to a public post on X."})
            return
        url = payload.get("url") if isinstance(payload, dict) else ""
        self._handle_rip(url if isinstance(url, str) else "")

    def _handle_rip(self, url: str):
        if self._limited():
            self._send_json(429, {"error": "Too many requests. Wait a minute and try again."})
            return
        try:
            post = extract(url)
        except RipError as err:
            self._send_json(err.status, {"error": str(err)})
            return
        self._send_json(200, post)

    def _handle_file(self, query: str, attachment: bool):
        params = urllib.parse.parse_qs(query)
        src = params.get("src", [""])[0]
        filename = safe_filename(params.get("filename", ["video.mp4"])[0])
        try:
            upstream = open_media(src, self.headers.get("Range"))
        except RipError as err:
            self._send_json(err.status, {"error": str(err)})
            return

        content_type = upstream.headers.get("Content-Type") or "video/mp4"
        if "mpegurl" in content_type:
            upstream.close()
            self._send_json(400, {"error": "That file link isn't allowed."})
            return

        status = getattr(upstream, "status", 200) or 200
        if status not in (200, 206):
            status = 200
        self.send_response(status)
        self.send_header("Content-Type", "video/mp4")
        disposition = "attachment" if attachment else "inline"
        self.send_header("Content-Disposition", f'{disposition}; filename="{filename}"')
        for header in ("Content-Length", "Content-Range", "Accept-Ranges"):
            value = upstream.headers.get(header)
            if value:
                self.send_header(header, value)
        self.send_header("Cache-Control", "private, max-age=300")
        self.end_headers()
        try:
            while True:
                chunk = upstream.read(64 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            upstream.close()

    def _serve_static(self, path: str):
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        if rel.startswith(".") or "\\" in rel:
            self._send_json(404, {"error": "Not found."})
            return
        target = (STATIC / rel).resolve()
        try:
            target.relative_to(STATIC)
        except ValueError:
            self._send_json(404, {"error": "Not found."})
            return
        if not target.is_file():
            self._send_json(404, {"error": "Not found."})
            return
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(target.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _limited(self) -> bool:
        now = time.monotonic()
        ip = self.client_address[0]
        with _lock:
            recent = [stamp for stamp in _hits.get(ip, []) if now - stamp < WINDOW_SECONDS]
            if len(recent) >= MAX_REQUESTS:
                _hits[ip] = recent
                return True
            recent.append(now)
            _hits[ip] = recent
            return False

    def log_message(self, fmt: str, *args):
        print(f"[{self.log_date_time_string()}] {self.address_string()} {fmt % args}")


def main():
    port = int(os.environ.get("PORT", "8787"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"X Ripper is running at http://localhost:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
