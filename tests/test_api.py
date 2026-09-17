"""HTTP client tests — no Blender required."""

from __future__ import annotations

import json
import os
import subprocess
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
        if self.path.startswith("/redirect-away"):
            self.send_response(302)
            self.send_header("Location", "https://evil.example/steal")
            self.end_headers()
            return
        if self.path.startswith("/thumb.png"):
            FakeAddonAPI.store["thumb_token"] = self.headers.get("X-Addon-Token")
            data = b"\x89PNG\r\n\x1a\n" + b"rest"
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path.startswith("/not-image"):
            data = b"<html>not an image</html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
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

    def test_blend_content_type_and_multipart_order(self):
        self.assertEqual(api.file_content_type("lamp.blend"), "application/x-blender")
        self.assertEqual(api.file_content_type("preview.png"), "image/png")
        body, ctype = api.encode_multipart(
            {"title": "Lamp"},
            [
                ("files", "preview.png", b"\x89PNG", "image/png"),
                ("files", "Lamp.blend", b"BLENDER-TEST", "application/x-blender"),
            ],
        )
        png_at = body.find(b"filename=\"preview.png\"")
        blend_at = body.find(b"filename=\"Lamp.blend\"")
        self.assertGreaterEqual(png_at, 0)
        self.assertGreater(blend_at, png_at)
        self.assertIn(b"application/x-blender", body)
        body, ctype = api.encode_multipart(
            {"title": "Chair"},
            [("files", "download.blend", b"ABC", "application/octet-stream")],
        )
        self.assertIn("multipart/form-data; boundary=", ctype)
        self.assertIn(b'name="title"', body)
        self.assertIn(b"filename=\"download.blend\"", body)
        self.assertIn(b"ABC", body)

    def test_listing_fields_thumbnail_first(self):
        fields = api.build_listing_fields(
            title="Lamp",
            description="A lamp",
            short_description="Lamp",
            price=0,
            category="cat_3d_models",
            tags="blender, pbr",
            rigged=True,
            license="CC_BY_40",
            texture_resolution="2K",
            pbr_workflow="metallic-roughness",
            polygon_count="1200",
            software_version="Blender 5.2.2",
            file_size="1.5 MB",
        )
        self.assertEqual(fields["category"], "3d-models")
        self.assertEqual(fields["license"], "CC BY 4.0")
        self.assertEqual(fields["pricingType"], "free")
        self.assertEqual(fields["rigged"], "true")
        self.assertEqual(fields["animated"], "false")
        self.assertEqual(fields["textureResolution"], "2K")
        self.assertEqual(fields["pbrWorkflow"], "metallic-roughness")
        self.assertEqual(fields["fileFormat"], "BLEND")
        compat = json.loads(fields["compatibility"])
        self.assertTrue(compat["blender"])
        self.assertFalse(compat["maya"])
        self.assertEqual(api.listing_category_slug("cat_textures"), "materials")
        self.assertEqual(api.license_api_value("CC_BY_SA_40"), "CC BY-SA 4.0")
        with tempfile.TemporaryDirectory() as tmp:
            png = Path(tmp) / "thumbnail.png"
            blend = Path(tmp) / "Lamp.blend"
            fake = Path(tmp) / "preview.png"
            png.write_bytes(api.PNG_MAGIC + b"rest")
            blend.write_bytes(b"BLENDER")
            fake.write_bytes(b"not-a-png")
            self.assertTrue(api.is_png_file(str(png)))
            self.assertFalse(api.is_png_file(str(fake)))
            paths = api.listing_file_paths(str(png), str(blend))
            self.assertEqual(paths[0], str(png))
            self.assertEqual(paths[1], str(blend))
            self.assertEqual(api.listing_file_paths(str(fake), str(blend)), [str(blend)])
            self.assertEqual(api.format_file_size(2048), "2 KB")

    def test_tag_normalize_and_suggest(self):
        self.assertEqual(api.normalize_tags("Blender, blender, PBR, pbr"), "blender, pbr")
        self.assertEqual(
            api.apply_suggested_tag("blender, ani", "animated"),
            "blender, animated",
        )
        self.assertEqual(api.apply_suggested_tag("blender", "pbr"), "blender, pbr")
        self.assertIn("animated", api.suggest_tags("blender, ani"))
        self.assertNotIn("blender", api.suggest_tags("blender"))
        collected = api.collect_tags(
            [{"tags": ["Low-Poly", "blender"]}, {"tags": "pbr, low-poly"}]
        )
        self.assertEqual(collected, ["low-poly", "blender", "pbr"])
        fields = api.build_listing_fields(title="X", tags="Blender, BLENDER, PBR")
        self.assertEqual(fields["tags"], "blender, pbr")

    def test_scene_heuristics(self):
        self.assertEqual(api.title_from_identifier("SM_Old_Hanging_Bar_Lamp.002"), "Old Hanging Bar Lamp")
        self.assertEqual(api.title_from_identifier("low_poly_tree_pack"), "Low Poly Tree Pack")
        self.assertEqual(api.format_polycount(12430), "12.4k")
        self.assertEqual(
            api.infer_category({"mesh_count": 2, "armature_count": 1, "rigged": True}),
            "3d-models",
        )
        self.assertEqual(
            api.infer_category({"mesh_count": 0, "armature_count": 1}),
            "rigs",
        )
        self.assertEqual(
            api.infer_category({"mesh_count": 12, "light_count": 2, "camera_count": 1}),
            "scenes",
        )
        tags = api.infer_tags(
            {"rigged": True, "pbr": True, "faces": 8000, "uv_unwrapped": True, "render_engine": "CYCLES"},
            ["hero_character"],
        )
        self.assertIn("rigged", tags)
        self.assertIn("pbr", tags)
        self.assertIn("hero", tags)
        short, description = api.listing_blurb(
            {"mesh_count": 2, "faces": 12430, "blender_version": "5.2.2", "pbr": True},
            "Lamp",
        )
        self.assertIn("Lamp", short)
        self.assertIn("12.4k", short)
        self.assertIn("12430 faces", description)

    def test_preview_file_helper(self):
        self.assertTrue(api.preview_file("/tmp/cache").endswith("preview.png"))

    def test_thumbs_imports_previews_submodule(self):
        text = (ROOT / "thumbs.py").read_text()
        self.assertIn("import bpy.utils.previews as previews", text)
        self.assertIn("_pcoll = previews.new()", text)

    def test_addon_versions_match(self):
        script = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "read_version.py"
        version = subprocess.check_output([sys.executable, str(script)], text=True).strip()
        self.assertEqual(version, api.ADDON_VERSION)

    def test_catalog_definition_text(self):
        text = api.catalog_definition_text()
        self.assertIn("VERSION 1", text)
        self.assertIn(api.CATALOG_UUID, text)
        self.assertIn("PolyAssetVault", text)
        self.assertTrue(text.endswith("\n"))

    def test_category_enum_roundtrip(self):
        self.assertEqual(api.category_enum_id("3d-models"), "cat_3d_models")
        self.assertEqual(api.category_api_slug("cat_3d_models"), "3d-models")
        self.assertEqual(api.category_api_slug("geometry-nodes"), "geometry-nodes")
        self.assertEqual(api.category_api_slug("ALL"), "")
        self.assertEqual(api.category_api_slug("0"), "")
        ids = [item[0] for item in api.category_enum_items()]
        self.assertTrue(all(ident.isidentifier() for ident in ids))
        self.assertIn("cat_3d_models", ids)

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

    def test_rejects_untrusted_urls_and_ids(self):
        self.assertIsNone(api.absolute_url("https://polyassetvault.com", "file:///etc/passwd"))
        self.assertIsNone(api.absolute_url("https://polyassetvault.com", "https://evil.example/x"))
        self.assertIsNone(api.absolute_url("https://polyassetvault.com", "javascript:alert(1)"))
        with self.assertRaises(api.AddonAPIError):
            api.validate_base_url("javascript:alert(1)")
        with self.assertRaises(api.AddonAPIError):
            api.validate_base_url("https://user:pass@polyassetvault.com")
        with self.assertRaises(api.AddonAPIError):
            api.validate_base_url("http://polyassetvault.com")
        self.assertTrue(api.validate_base_url("http://127.0.0.1:5000").startswith("http://127.0.0.1"))
        with self.assertRaises(api.AddonAPIError):
            api.login_page_url("javascript:alert(1)", 55555, "abc")
        with self.assertRaises(api.AddonAPIError):
            api.path_segment("../admin")
        with self.assertRaises(api.AddonAPIError):
            api.path_segment("a/b")
        self.assertEqual(api.path_segment("p1"), "p1")
        self.assertEqual(api.safe_asset_filename("..", "download.bin"), "download.bin")
        self.assertEqual(api.safe_asset_filename("../../../etc/passwd", "x.blend"), "x.blend")
        self.assertEqual(api.safe_asset_filename("chair.blend", "download.bin"), "chair.blend")
        fields = api.build_listing_fields(title="X", video_preview_url="javascript:https://evil.example")
        self.assertNotIn("videoPreviewUrl", fields)

    def test_download_to_blocks_foreign_and_file_urls(self):
        client = api.AddonClient(self.base, token="device-token-abc")
        with tempfile.TemporaryDirectory() as tmp:
            dest = str(Path(tmp) / "preview.png")
            with self.assertRaises(api.AddonAPIError):
                client.download_to("https://evil.example/thumb.png", dest)
            with self.assertRaises(api.AddonAPIError):
                client.download_to("file:///etc/passwd", dest)
            with self.assertRaises(api.AddonAPIError):
                client.download_to("http://127.0.0.1:9/thumb.png", dest)

    def test_download_to_omits_token_and_requires_image(self):
        client = api.AddonClient(self.base, token="device-token-abc")
        with tempfile.TemporaryDirectory() as tmp:
            dest = str(Path(tmp) / "preview.png")
            saved = client.download_to("/thumb.png", dest)
            self.assertEqual(saved, dest)
            self.assertTrue(Path(dest).read_bytes().startswith(api.PNG_MAGIC))
            self.assertIsNone(FakeAddonAPI.store.get("thumb_token"))
            bad = str(Path(tmp) / "bad.png")
            with self.assertRaises(api.AddonAPIError):
                client.download_to("/not-image", bad)
            self.assertFalse(Path(bad).exists())

    def test_mark_blend_disables_autoexec(self):
        text = (ROOT / "assets.py").read_text()
        self.assertIn("--disable-autoexec", text)

    def test_blocks_cross_origin_redirect(self):
        client = api.AddonClient(self.base, token="device-token-abc")
        with self.assertRaises(api.AddonAPIError) as ctx:
            client.request_json("GET", "/redirect-away")
        self.assertIn("redirect", str(ctx.exception).lower())

    def test_safe_extract_rejects_zip_slip(self):
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / "evil.zip"
            dest = Path(tmp) / "out"
            dest.mkdir()
            import zipfile

            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("../evil.txt", "nope")
                zf.writestr("ok.blend", "BLEND")
            with self.assertRaises(api.AddonAPIError):
                api.safe_extract_zip(str(zip_path), str(dest))
            self.assertFalse((Path(tmp) / "evil.txt").exists())
            self.assertFalse((dest / "ok.blend").exists())

    def test_safe_extract_keeps_nested_blend(self):
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / "ok.zip"
            dest = Path(tmp) / "out"
            dest.mkdir()
            import zipfile

            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("folder/model.blend", b"BLEND")
            api.safe_extract_zip(str(zip_path), str(dest))
            self.assertEqual((dest / "folder" / "model.blend").read_bytes(), b"BLEND")


if __name__ == "__main__":
    unittest.main()
