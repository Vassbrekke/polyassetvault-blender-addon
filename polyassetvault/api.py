"""PolyAssetVault addon HTTP client. Stdlib only — no bpy, so unit tests can import it."""

from __future__ import annotations

import json
import mimetypes
import os
import re
import secrets
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable, Mapping, Optional

ADDON_VERSION = "0.3.1"
USER_AGENT = f"PolyAssetVault-Blender/{ADDON_VERSION}"
DEFAULT_TIMEOUT = 30
TRANSFER_TIMEOUT = 300
LIBRARY_NAME = "PolyAssetVault"
CATALOG_UUID = "7c2e9a10-4f3b-4c8d-9e21-00c0ffee0001"
PREVIEW_FILENAME = "preview.png"


def catalog_definition_text(uuid: str = CATALOG_UUID, name: str = LIBRARY_NAME) -> str:
    return (
        "# This is an Asset Catalog Definition file for Blender.\n"
        "VERSION 1\n"
        f"{uuid}:{name}:{name}\n"
    )

CATEGORIES = (
    "3d-models",
    "textures",
    "materials",
    "animations",
    "rigs",
    "scenes",
    "geometry-nodes",
    "vfx",
    "hdri",
    "addons",
    "other",
)


def category_enum_id(slug: str) -> str:
    """Blender EnumProperty identifiers must be valid Python identifiers (no hyphens, no leading digit)."""
    return "cat_" + (slug or "other").replace("-", "_")


def category_api_slug(enum_id: str) -> str:
    """Map an enum identifier (or a raw slug) back to the API category."""
    if not enum_id or enum_id in ("ALL", "0"):
        return ""
    if enum_id in CATEGORIES:
        return enum_id
    raw = enum_id[4:] if enum_id.startswith("cat_") else enum_id
    slug = raw.replace("_", "-")
    if slug in CATEGORIES:
        return slug
    return "other"


def category_enum_items():
    return tuple(
        (category_enum_id(c), c.replace("-", " ").title(), "") for c in CATEGORIES
    )


class AddonAPIError(Exception):
    def __init__(self, status: int, message: str, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.payload = payload

    def __str__(self) -> str:
        return f"HTTP {self.status}: {self.message}"


def join_url(base: str, path: str) -> str:
    base = (base or "").rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return base + path


def absolute_url(base: str, maybe_relative: Optional[str]) -> Optional[str]:
    if not maybe_relative:
        return None
    if maybe_relative.startswith("http://") or maybe_relative.startswith("https://"):
        return maybe_relative
    return join_url(base, maybe_relative)


def encode_multipart(
    fields: Mapping[str, str],
    files: Iterable[tuple[str, str, bytes, str]],
) -> tuple[bytes, str]:
    """Return (body, content_type) for multipart/form-data.

    files items: (field_name, filename, content, content_type)
    """
    boundary = "----PavBoundary" + secrets.token_hex(16)
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8")
        )
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")
    for field_name, filename, content, content_type in files:
        safe_name = os.path.basename(filename).replace('"', "")
        ctype = content_type or "application/octet-stream"
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            (
                f'Content-Disposition: form-data; name="{field_name}"; '
                f'filename="{safe_name}"\r\n'
                f"Content-Type: {ctype}\r\n\r\n"
            ).encode("utf-8")
        )
        chunks.append(content)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(chunks)
    return body, f"multipart/form-data; boundary={boundary}"


def file_content_type(filename: str) -> str:
    name = (filename or "").lower()
    if name.endswith(".blend"):
        return "application/x-blender"
    guessed = mimetypes.guess_type(filename or "")[0]
    return guessed or "application/octet-stream"


def _filename_from_disposition(header: Optional[str], fallback: str) -> str:
    if not header:
        return fallback
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', header, re.I)
    if not match:
        match = re.search(r'filename="([^"]+)"', header, re.I)
    if match:
        name = os.path.basename(urllib.parse.unquote(match.group(1).strip()))
        return name or fallback
    return fallback


class AddonClient:
    def __init__(
        self,
        api_base: str,
        token: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT,
        opener: Optional[urllib.request.OpenerDirector] = None,
    ):
        self.api_base = (api_base or "").rstrip("/")
        self.token = token or ""
        self.timeout = timeout
        self._opener = opener or urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ssl.create_default_context())
        )

    def _headers(self, extra: Optional[Mapping[str, str]] = None) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        if self.token:
            headers["X-Addon-Token"] = self.token
        if extra:
            headers.update(extra)
        return headers

    def _open(self, req: urllib.request.Request, timeout: Optional[int] = None):
        try:
            return self._opener.open(req, timeout=timeout if timeout is not None else self.timeout)
        except urllib.error.HTTPError as exc:
            payload = None
            message = exc.reason or "Request failed"
            try:
                raw = exc.read()
                if raw:
                    payload = json.loads(raw.decode("utf-8"))
                    message = (
                        payload.get("message")
                        or payload.get("error")
                        or message
                    )
            except Exception:
                payload = None
            raise AddonAPIError(exc.code, str(message), payload) from exc
        except urllib.error.URLError as exc:
            raise AddonAPIError(0, f"Network error: {exc.reason}") from exc

    def request_json(
        self,
        method: str,
        path: str,
        *,
        query: Optional[Mapping[str, Any]] = None,
        json_body: Any = None,
        bearer: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> Any:
        url = join_url(self.api_base, path)
        if query:
            filtered = {k: v for k, v in query.items() if v is not None and v != ""}
            if filtered:
                url += "?" + urllib.parse.urlencode(filtered)
        data = None
        extra = {}
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            extra["Content-Type"] = "application/json"
        if bearer:
            extra["Authorization"] = f"Bearer {bearer}"
        req = urllib.request.Request(
            url,
            data=data,
            headers=self._headers(extra),
            method=method.upper(),
        )
        with self._open(req, timeout=timeout) as resp:
            raw = resp.read()
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))

    def request_multipart(
        self,
        method: str,
        path: str,
        fields: Mapping[str, str],
        files: Iterable[tuple[str, str, bytes, str]],
        timeout: int = TRANSFER_TIMEOUT,
    ) -> Any:
        body, content_type = encode_multipart(fields, files)
        url = join_url(self.api_base, path)
        req = urllib.request.Request(
            url,
            data=body,
            headers=self._headers({"Content-Type": content_type}),
            method=method.upper(),
        )
        with self._open(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            raw = resp.read()
            if not raw:
                return {"_http_status": status}
            payload = json.loads(raw.decode("utf-8"))
            if isinstance(payload, dict):
                payload["_http_status"] = status
            return payload

    def download_file(self, path: str, dest_path: str, timeout: int = TRANSFER_TIMEOUT) -> str:
        url = join_url(self.api_base, path)
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        os.makedirs(os.path.dirname(os.path.abspath(dest_path)) or ".", exist_ok=True)
        with self._open(req, timeout=timeout) as resp:
            filename = _filename_from_disposition(
                resp.headers.get("Content-Disposition"),
                os.path.basename(dest_path) or "download",
            )
            directory = os.path.dirname(os.path.abspath(dest_path))
            final_path = os.path.join(directory, filename)
            with open(final_path, "wb") as handle:
                while True:
                    chunk = resp.read(1024 * 256)
                    if not chunk:
                        break
                    handle.write(chunk)
        return final_path

    def download_to(self, url_or_path: str, dest_path: str, timeout: int = DEFAULT_TIMEOUT) -> str:
        url = url_or_path or ""
        if url.startswith("/"):
            url = join_url(self.api_base, url)
        if not url:
            raise AddonAPIError(0, "No download URL")
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        directory = os.path.dirname(os.path.abspath(dest_path)) or "."
        os.makedirs(directory, exist_ok=True)
        with self._open(req, timeout=timeout) as resp:
            with open(dest_path, "wb") as handle:
                while True:
                    chunk = resp.read(1024 * 256)
                    if not chunk:
                        break
                    handle.write(chunk)
        return dest_path

    # ── Auth ────────────────────────────────────────────────────────────────

    def issue_device_token(
        self,
        jwt: str,
        *,
        device_name: str = "Blender Addon",
        blender_version: str = "",
        addon_version: str = ADDON_VERSION,
        platform: str = "",
    ) -> dict:
        return self.request_json(
            "POST",
            "/api/addon/auth/device-token",
            json_body={
                "deviceName": device_name,
                "blenderVersion": blender_version,
                "addonVersion": addon_version,
                "platform": platform,
            },
            bearer=jwt,
        )

    def me(self) -> dict:
        return self.request_json("GET", "/api/addon/auth/me")

    def logout(self) -> dict:
        return self.request_json("DELETE", "/api/addon/auth/device-token")

    # ── Catalog ─────────────────────────────────────────────────────────────

    def browse(
        self,
        *,
        search: str = "",
        category: str = "",
        page: int = 1,
        limit: int = 20,
    ) -> dict:
        return self.request_json(
            "GET",
            "/api/addon/products",
            query={"search": search, "category": category, "page": page, "limit": limit},
        )

    def product(self, product_id: str) -> dict:
        return self.request_json("GET", f"/api/addon/products/{product_id}")

    def purchases(self) -> dict:
        return self.request_json("GET", "/api/addon/purchases")

    def my_products(self, *, status: str = "", page: int = 1, limit: int = 50) -> dict:
        return self.request_json(
            "GET",
            "/api/addon/my-products",
            query={"status": status, "page": page, "limit": limit},
        )

    def download_product(self, product_id: str, dest_path: str) -> str:
        return self.download_file(f"/api/addon/products/{product_id}/download", dest_path)

    def create_product(
        self,
        fields: Mapping[str, str],
        file_paths: Iterable[str],
    ) -> dict:
        files = []
        for path in file_paths:
            name = os.path.basename(path)
            ctype = file_content_type(name)
            with open(path, "rb") as handle:
                files.append(("files", name, handle.read(), ctype))
        return self.request_multipart("POST", "/api/addon/products", fields, files)

    def update_product(
        self,
        product_id: str,
        fields: Mapping[str, str],
        file_paths: Iterable[str] = (),
    ) -> dict:
        files = []
        for path in file_paths:
            name = os.path.basename(path)
            ctype = file_content_type(name)
            with open(path, "rb") as handle:
                files.append(("files", name, handle.read(), ctype))
        return self.request_multipart(
            "PUT", f"/api/addon/products/{product_id}", fields, files
        )


def safe_product_id(product_id: str) -> str:
    text = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(product_id or ""))
    return text or "product"


def product_cache_dir(download_dir: str, product_id: str) -> str:
    return os.path.join(download_dir, safe_product_id(product_id))


def preview_file(cache_dir: str) -> str:
    return os.path.join(cache_dir, PREVIEW_FILENAME)


def find_cached_asset(cache_dir: str) -> Optional[str]:
    """Return the first .blend or .zip in a product cache folder."""
    if not cache_dir or not os.path.isdir(cache_dir):
        return None
    blends: list[str] = []
    zips: list[str] = []
    try:
        names = os.listdir(cache_dir)
    except OSError:
        return None
    for name in sorted(names):
        path = os.path.join(cache_dir, name)
        if not os.path.isfile(path):
            continue
        lower = name.lower()
        if lower.endswith(".blend"):
            blends.append(path)
        elif lower.endswith(".zip"):
            zips.append(path)
    if blends:
        return blends[0]
    if zips:
        return zips[0]
    return None


def product_page_url(site_url: str, product_id: str) -> str:
    return join_url(site_url, f"/product/{product_id}")


def login_page_url(site_url: str, port: int, state: str) -> str:
    query = urllib.parse.urlencode({"port": port, "state": state})
    return join_url(site_url, f"/addon-login?{query}")
