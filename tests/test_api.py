"""HTTP client tests — no Blender required."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "polyassetvault"
sys.path.insert(0, str(ROOT))

import api  # noqa: E402


class FakeAddonAPI(BaseHTTPRequestHandler):
    store = {
        "token": "device-token-abc",
        "jwt": "jwt-from-browser",
        "last": None,
    }

    def log_message(self, format, *args):  # noqa: A002
        return

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _send(self, code, payload, extra_headers=None):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        FakeAddonAPI.store["last"] = ("GET", self.path, self.headers.get("X-Addon-Token"))
        if self.path.startswith("/api/addon/auth/me"):
            if self.headers.get("X-Addon-Token") != self.store["token"]:
                return self._send(401, {"message": "Invalid addon device token."})
            return self._send(200, {"username": "sindre", "userType": "creator", "stripeConnected": True})
        if self.path.startswith("/api/addon/purchases"):
            return self._send(
                200,
                {
                    "purchases": [
                        {
                            "productId": "p1",
                            "title": "Chair",
                            "price": 12,
                            "currency": "USD",
                            "author": "studio",
                        }
                    ],
                    "total": 1,
                },
            )
        if self.path.startswith("/api/addon/products/p1/download"):
            data = b"BLENDFILE"
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", 'attachment; filename="chair.blend"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path.startswith("/api/addon/products/p1"):
            return self._send(200, {"productId": "p1", "title": "Chair", "owned": True, "price": 12})
        if self.path.startswith("/api/addon/products"):
            return self._send(
                200,
                {
                    "products": [{"productId": "p1", "title": "Chair", "price": 12, "currency": "USD"}],
                    "total": 1,
                    "page": 1,
                    "pages": 1,
                },
            )
        if self.path.startswith("/api/addon/my-products"):
            return self._send(200, {"products": [], "total": 0, "totalPages": 0, "currentPage": 1})
        self._send(404, {"message": "not found"})

    def do_POST(self):
        FakeAddonAPI.store["last"] = ("POST", self.path, self.headers.get("Authorization"))
        if self.path == "/api/addon/auth/device-token":
            auth = self.headers.get("Authorization") or ""
            if auth != f"Bearer {self.store['jwt']}":
                return self._send(401, {"message": "Not authorized"})
            body = self._read_json()
            FakeAddonAPI.store["issued_meta"] = body
            return self._send(
                201,
                {
                    "deviceToken": self.store["token"],
                    "username": "sindre",
                    "userType": "creator",
                },
            )
        if self.path == "/api/addon/products":
            if self.headers.get("X-Addon-Token") != self.store["token"]:
                return self._send(401, {"message": "Invalid addon device token."})
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            FakeAddonAPI.store["upload"] = raw
            ctype = self.headers.get("Content-Type") or ""
            if "multipart/form-data" not in ctype:
                return self._send(400, {"message": "Expected multipart"})
            if b"download.blend" not in raw or b'name="title"' not in raw:
                return self._send(400, {"message": "Missing blend or title"})
            return self._send(201, {"_id": "new1", "title": "From Blender", "status": "draft"})
        self._send(404, {"message": "not found"})

    def do_DELETE(self):
        if self.path == "/api/addon/auth/device-token":
            if self.headers.get("X-Addon-Token") != self.store["token"]:
                return self._send(401, {"message": "Invalid addon device token."})
            return self._send(200, {"message": "Logged out successfully."})
        self._send(404, {"message": "not found"})


def start_fake():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeAddonAPI)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host = httpd.server_address[0]
    port = httpd.server_address[1]
    return httpd, f"http://{host}:{port}"


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd, cls.base = start_fake()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_join_and_login_urls(self):
        self.assertEqual(api.join_url("https://polyassetvault.com/", "/api/addon/me"), "https://polyassetvault.com/api/addon/me")
        url = api.login_page_url("https://polyassetvault.com", 55555, "abc")
        self.assertIn("port=55555", url)
        self.assertIn("state=abc", url)
        self.assertTrue(url.startswith("https://polyassetvault.com/addon-login?"))
        self.assertEqual(
            api.product_page_url("https://polyassetvault.com", "xyz"),
            "https://polyassetvault.com/product/xyz",
        )

    def test_absolute_thumbnail(self):
        self.assertEqual(
            api.absolute_url("https://polyassetvault.com", "/api/images/1/2?size=256"),
            "https://polyassetvault.com/api/images/1/2?size=256",
        )

    def test_issue_device_token_and_me(self):
        client = api.AddonClient(self.base)
        issued = client.issue_device_token("jwt-from-browser", device_name="Blender 4.2")
        self.assertEqual(issued["deviceToken"], "device-token-abc")
        authed = api.AddonClient(self.base, token=issued["deviceToken"])
        me = authed.me()
        self.assertEqual(me["username"], "sindre")
        self.assertTrue(me["stripeConnected"])

    def test_rejects_missing_token(self):
        client = api.AddonClient(self.base)
        with self.assertRaises(api.AddonAPIError) as ctx:
            client.me()
        self.assertEqual(ctx.exception.status, 401)

    def test_browse_purchases_product(self):
        client = api.AddonClient(self.base, token="device-token-abc")
        browse = client.browse(search="chair")
        self.assertEqual(browse["products"][0]["title"], "Chair")
        purchases = client.purchases()
        self.assertEqual(purchases["total"], 1)
        detail = client.product("p1")
        self.assertTrue(detail["owned"])

    def test_download_uses_content_disposition_name(self):
        client = api.AddonClient(self.base, token="device-token-abc")
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "download.bin"
            saved = client.download_product("p1", str(dest))
            self.assertTrue(saved.endswith("chair.blend"))
            self.assertEqual(Path(saved).read_bytes(), b"BLENDFILE")

    def test_create_product_multipart(self):
        client = api.AddonClient(self.base, token="device-token-abc")
        with tempfile.TemporaryDirectory() as tmp:
            blend = Path(tmp) / "download.blend"
            blend.write_bytes(b"BLENDER-TEST")
            created = client.create_product(
                {
                    "title": "From Blender",
                    "price": "0",
                    "category": "3d-models",
                    "status": "draft",
                },
                [str(blend)],
            )
        self.assertEqual(created["_id"], "new1")

    def test_logout(self):
        client = api.AddonClient(self.base, token="device-token-abc")
        payload = client.logout()
        self.assertIn("Logged out", payload["message"])

    def test_encode_multipart_roundtrip_markers(self):
        body, ctype = api.encode_multipart(
            {"title": "Chair"},
            [("files", "download.blend", b"ABC", "application/octet-stream")],
        )
        self.assertIn("multipart/form-data; boundary=", ctype)
        self.assertIn(b'name="title"', body)
        self.assertIn(b"filename=\"download.blend\"", body)
        self.assertIn(b"ABC", body)

    def test_product_cache_prefers_blend(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = api.product_cache_dir(tmp, "abc/../../evil id")
            os.makedirs(cache, exist_ok=True)
            (Path(cache) / "note.txt").write_text("x")
            zip_path = Path(cache) / "pack.zip"
            zip_path.write_bytes(b"PK")
            blend_path = Path(cache) / "model.blend"
            blend_path.write_bytes(b"BLEND")
            self.assertEqual(api.safe_product_id("abc/../../evil id"), "abc_______evil_id")
            self.assertEqual(api.find_cached_asset(cache), str(blend_path))
            self.assertIsNone(api.find_cached_asset(tmp))
            self.assertTrue(cache.startswith(tmp))
            self.assertNotIn("..", os.path.relpath(cache, tmp))


if __name__ == "__main__":
    unittest.main()
