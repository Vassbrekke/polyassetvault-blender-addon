"""Localhost callback server for the existing /addon-login browser flow.

The frontend redirects to http://localhost:<port>/callback?token=<jwt>&state=<state>
on a port in 49152–65535. This module is stdlib-only (no bpy).
"""

from __future__ import annotations

import html
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PORT_MIN = 49152
PORT_MAX = 65535
DEFAULT_TTL_SECONDS = 180
MAX_TOKEN_LEN = 16384


class LoginCallback:
    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self.state = secrets.token_urlsafe(24)
        self.ttl_seconds = ttl_seconds
        self.started_at = 0.0
        self.port = 0
        self.token: str | None = None
        self.error: str | None = None
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> int:
        last_error = None
        for _ in range(24):
            port = secrets.randbelow(PORT_MAX - PORT_MIN + 1) + PORT_MIN
            try:
                httpd = ThreadingHTTPServer(("127.0.0.1", port), self._handler_class())
                httpd.allow_reuse_address = True
                self._httpd = httpd
                self.port = port
                break
            except OSError as exc:
                last_error = exc
                continue
        if self._httpd is None:
            raise RuntimeError(f"Could not bind addon callback port ({last_error})")

        self.started_at = time.time()
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self.port

    def poll(self) -> str | None:
        with self._lock:
            return self.token

    def expired(self) -> bool:
        if not self.started_at:
            return False
        return (time.time() - self.started_at) > self.ttl_seconds

    def stop(self) -> None:
        httpd = self._httpd
        self._httpd = None
        if httpd is not None:
            try:
                httpd.shutdown()
            except Exception:
                pass
            try:
                httpd.server_close()
            except Exception:
                pass

    def _handler_class(self):
        callback = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):  # noqa: A002, N802 — never log callback URLs
                return

            def do_GET(self):  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path != "/callback":
                    self.send_error(404, "Not found")
                    return
                host_header = (self.headers.get("Host") or "").split(":")[0].strip().lower()
                if host_header not in ("127.0.0.1", "localhost"):
                    self.send_error(403, "Forbidden")
                    return
                host = self.client_address[0]
                if host not in ("127.0.0.1", "::1"):
                    self.send_error(403, "Forbidden")
                    return
                params = parse_qs(parsed.query, keep_blank_values=False)
                state = (params.get("state") or [""])[0]
                token = (params.get("token") or [""])[0]
                expected = callback.state.encode("utf-8")
                given = state.encode("utf-8")
                if (
                    not state
                    or len(given) != len(expected)
                    or not secrets.compare_digest(given, expected)
                ):
                    callback.error = "State mismatch"
                    self._html(400, "Login failed", "State mismatch. Return to Blender and try again.")
                    return
                if not token or len(token) > MAX_TOKEN_LEN or any(ch.isspace() for ch in token):
                    callback.error = "Missing token"
                    self._html(400, "Login failed", "No token was returned.")
                    return
                with callback._lock:
                    if callback.token is not None:
                        already = True
                    else:
                        callback.token = token
                        already = False
                if already:
                    self._html(409, "Already used", "This sign-in was already completed.")
                    return
                self._html(
                    200,
                    "Signed in",
                    "You can close this tab and return to Blender.",
                )

            def _html(self, code: int, title: str, body: str) -> None:
                title = html.escape(title, quote=True)
                body = html.escape(body, quote=True)
                page = (
                    "<!DOCTYPE html><html><head><meta charset='utf-8'>"
                    f"<title>{title}</title></head><body>"
                    f"<h1>{title}</h1><p>{body}</p></body></html>"
                ).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", "default-src 'none'")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                self.wfile.write(page)

        return Handler


def port_in_addon_range(port: int) -> bool:
    return isinstance(port, int) and PORT_MIN <= port <= PORT_MAX


def unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
