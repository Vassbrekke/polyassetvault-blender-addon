"""Localhost callback server tests — no Blender required."""

from __future__ import annotations

import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1] / "polyassetvault"
sys.path.insert(0, str(ROOT))

import auth  # noqa: E402
import unittest


class AuthServerTests(unittest.TestCase):
    def test_port_range_helper(self):
        self.assertTrue(auth.port_in_addon_range(49152))
        self.assertTrue(auth.port_in_addon_range(65535))
        self.assertFalse(auth.port_in_addon_range(80))
        self.assertFalse(auth.port_in_addon_range(49151))

    def test_callback_captures_token_and_rejects_bad_state(self):
        callback = auth.LoginCallback(ttl_seconds=30)
        port = callback.start()
        self.addCleanup(callback.stop)
        self.assertTrue(auth.port_in_addon_range(port))

        bad = urlencode({"token": "should-not-store", "state": "wrong"})
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/callback?{bad}", timeout=5)
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 400)
        self.assertIsNone(callback.poll())

        good = urlencode({"token": "jwt-value", "state": callback.state})
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/callback?{good}", timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            html = resp.read().decode("utf-8")
            self.assertIn("Signed in", html)
            self.assertNotIn("jwt-value", html)
        self.assertEqual(callback.poll(), "jwt-value")

        second = urlencode({"token": "other-jwt", "state": callback.state})
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/callback?{second}", timeout=5)
            reused = True
        except urllib.error.HTTPError as exc:
            reused = False
            self.assertEqual(exc.code, 409)
        self.assertFalse(reused)
        self.assertEqual(callback.poll(), "jwt-value")

    def test_callback_rejects_foreign_host_header(self):
        callback = auth.LoginCallback(ttl_seconds=30)
        port = callback.start()
        self.addCleanup(callback.stop)
        good = urlencode({"token": "jwt-value", "state": callback.state})
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/callback?{good}",
            headers={"Host": "evil.example"},
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 403)
        self.assertIsNone(callback.poll())

    def test_unknown_path_is_404(self):
        callback = auth.LoginCallback(ttl_seconds=30)
        port = callback.start()
        self.addCleanup(callback.stop)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/nope", timeout=5)
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
