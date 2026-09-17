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

ADDON_VERSION = "0.3.4"
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


# Product.category on the server has no "textures" (browse still lists it).
PRODUCT_CATEGORIES = (
    "3d-models",
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
CATEGORY_POST_ALIASES = {"textures": "materials"}

LICENSE_ENUM = (
    ("CC0", "CC0", "Public domain"),
    ("CC_BY_40", "CC BY 4.0", "Attribution"),
    ("CC_BY_SA_40", "CC BY-SA 4.0", "Attribution-ShareAlike"),
    ("CC_BY_NC_40", "CC BY-NC 4.0", "Attribution-NonCommercial"),
    ("CC_BY_NC_SA_40", "CC BY-NC-SA 4.0", "Attribution-NonCommercial-ShareAlike"),
    ("CC_BY_ND_40", "CC BY-ND 4.0", "Attribution-NoDerivatives"),
    ("CC_BY_NC_ND_40", "CC BY-NC-ND 4.0", "Attribution-NonCommercial-NoDerivatives"),
)
LICENSE_API = {
    "CC0": "CC0",
    "CC_BY_40": "CC BY 4.0",
    "CC_BY_SA_40": "CC BY-SA 4.0",
    "CC_BY_NC_40": "CC BY-NC 4.0",
    "CC_BY_NC_SA_40": "CC BY-NC-SA 4.0",
    "CC_BY_ND_40": "CC BY-ND 4.0",
    "CC_BY_NC_ND_40": "CC BY-NC-ND 4.0",
}
TEXTURE_RES_API = {
    "res_1K": "1K",
    "res_2K": "2K",
    "res_4K": "4K",
    "res_8K": "8K",
    "res_procedural": "procedural",
}
PBR_API = {
    "metallic_roughness": "metallic-roughness",
    "specular_glossiness": "specular-glossiness",
}
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def listing_category_slug(enum_id: str) -> str:
    slug = category_api_slug(enum_id) or "3d-models"
    slug = CATEGORY_POST_ALIASES.get(slug, slug)
    if slug not in PRODUCT_CATEGORIES:
        return "other"
    return slug


def license_api_value(enum_id: str) -> str:
    return LICENSE_API.get(enum_id or "", "CC BY 4.0")


def texture_resolution_api(enum_id: str) -> str:
    return TEXTURE_RES_API.get(enum_id or "", "")


def pbr_workflow_api(enum_id: str) -> str:
    return PBR_API.get(enum_id or "", "")


def is_png_file(path: str) -> bool:
    if not path or not os.path.isfile(path):
        return False
    try:
        with open(path, "rb") as handle:
            return handle.read(8) == PNG_MAGIC
    except OSError:
        return False


def listing_file_paths(thumbnail_path: str, blend_path: str) -> list[str]:
    """PNG thumbnail first (Market treats files[0] as the listing thumb), then .blend."""
    paths: list[str] = []
    if is_png_file(thumbnail_path):
        paths.append(thumbnail_path)
    if blend_path and os.path.isfile(blend_path):
        paths.append(blend_path)
    return paths


def format_file_size(nbytes: int) -> str:
    size = max(int(nbytes or 0), 0)
    if size < 1024:
        return f"{size} Bytes"
    units = ("KB", "MB", "GB")
    value = float(size)
    for unit in units:
        value /= 1024.0
        if value < 1024 or unit == "GB":
            pretty = f"{value:.2f}".rstrip("0").rstrip(".")
            return f"{pretty} {unit}"
    return f"{size} Bytes"


SEED_TAGS = (
    "blender",
    "3d",
    "pbr",
    "rigged",
    "animated",
    "low-poly",
    "game-ready",
    "stylized",
    "realistic",
    "character",
    "environment",
    "prop",
    "vehicle",
    "architecture",
    "nature",
    "sci-fi",
    "interior",
)


def split_tags(text: str) -> list[str]:
    parts: list[str] = []
    for raw in (text or "").split(","):
        tag = " ".join(raw.strip().lower().split())
        if tag and tag not in parts:
            parts.append(tag)
    return parts


def normalize_tags(text: str, known: Iterable[str] = ()) -> str:
    lookup = {}
    for item in list(SEED_TAGS) + list(known or []):
        key = " ".join(str(item).strip().lower().split())
        if key:
            lookup[key] = key
    out: list[str] = []
    for tag in split_tags(text):
        canon = lookup.get(tag, tag)
        if canon not in out:
            out.append(canon)
    return ", ".join(out)


def suggest_tags(text: str, known: Iterable[str] = (), limit: int = 8) -> list[str]:
    used = set(split_tags(text))
    raw = text or ""
    prefix = "" if raw.endswith(",") else raw.split(",")[-1].strip().lower()
    catalog: list[str] = []
    seen: set[str] = set()
    for item in list(SEED_TAGS) + list(known or []):
        tag = " ".join(str(item).strip().lower().split())
        if tag and tag not in seen:
            catalog.append(tag)
            seen.add(tag)
    matches: list[str] = []
    for tag in catalog:
        if tag in used:
            continue
        if prefix and not (tag.startswith(prefix) or prefix in tag):
            continue
        matches.append(tag)
        if len(matches) >= limit:
            break
    return matches


def apply_suggested_tag(current: str, suggestion: str, known: Iterable[str] = ()) -> str:
    suggestion = " ".join((suggestion or "").strip().lower().split())
    if not suggestion:
        return normalize_tags(current, known)
    raw = current or ""
    if not raw.strip() or raw.endswith(",") or raw.endswith(", "):
        return normalize_tags(raw + " " + suggestion, known)
    parts = raw.split(",")
    last = parts[-1].strip().lower()
    if last and suggestion.startswith(last):
        parts[-1] = " " + suggestion
        return normalize_tags(",".join(parts), known)
    return normalize_tags(raw + ", " + suggestion, known)


def collect_tags(products: Iterable[Mapping[str, Any]]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for product in products or []:
        tags = product.get("tags") or []
        if isinstance(tags, str):
            tags = split_tags(tags)
        for tag in tags:
            item = " ".join(str(tag).strip().lower().split())
            if item and item not in seen:
                seen.add(item)
                found.append(item)
    return found


_NAME_SUFFIX = re.compile(r"\.\d{3}$")
_NAME_PREFIXES = ("SM_", "SK_", "SKM_", "SKEL_", "GEO_", "MESH_", "MAT_", "CAM_", "LG_", "BP_")
_TAG_STOP = {
    "cube", "sphere", "plane", "light", "camera", "empty", "bezier", "nurbs",
    "circle", "untitled", "asset", "mesh", "object", "scene", "collection",
    "material", "the", "and", "for", "obj", "blend",
}


def title_from_identifier(name: str) -> str:
    text = _NAME_SUFFIX.sub("", str(name or ""))
    upper = text.upper()
    for prefix in _NAME_PREFIXES:
        if upper.startswith(prefix):
            text = text[len(prefix):]
            break
    text = re.sub(r"[_-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return "Untitled asset"
    return text.title()


def name_tokens(*parts: Any) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for part in parts:
        for raw in re.split(r"[^a-z0-9]+", str(part or "").lower()):
            if len(raw) < 3 or raw in _TAG_STOP or raw in seen:
                continue
            seen.add(raw)
            tokens.append(raw)
    return tokens


def infer_category(meta: Mapping[str, Any], names: Iterable[str] = ()) -> str:
    hay = " ".join(str(n).lower() for n in names)
    meshes = int(meta.get("mesh_count") or 0)
    mats = int(meta.get("material_count") or 0)
    armatures = int(meta.get("armature_count") or 0)
    if meshes == 0 and meta.get("world_hdri"):
        return "hdri"
    if meshes == 0 and mats > 0:
        return "materials"
    if meshes == 0 and armatures > 0:
        return "rigs"
    if meshes == 0 and meta.get("animated"):
        return "animations"
    if meshes == 0 and meta.get("geometry_nodes"):
        return "geometry-nodes"
    if meshes > 8 and int(meta.get("light_count") or 0) > 0 and int(meta.get("camera_count") or 0) > 0:
        return "scenes"
    if "hdri" in hay or "environment map" in hay:
        return "hdri"
    if any(word in hay for word in ("vfx", "particle", "fx")):
        return "vfx"
    if "geonode" in hay or "geometry node" in hay:
        return "geometry-nodes"
    return "3d-models"


def infer_tags(meta: Mapping[str, Any], names: Iterable[str] = ()) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()

    def add(tag: str) -> None:
        item = " ".join(str(tag).strip().lower().split())
        if item and item not in seen and item not in _TAG_STOP:
            seen.add(item)
            tags.append(item)

    add("blender")
    add("3d")
    for token in name_tokens(*list(names or [])):
        add(token)
        if len(tags) >= 10:
            break
    if meta.get("rigged"):
        add("rigged")
    if meta.get("animated"):
        add("animated")
    if meta.get("pbr"):
        add("pbr")
    if meta.get("uv_unwrapped"):
        add("uv-mapped")
    if meta.get("geometry_nodes"):
        add("geometry-nodes")
    if meta.get("shape_keys"):
        add("shapekeys")
    if meta.get("hair"):
        add("hair")
    if meta.get("lods"):
        add("lod")
    if meta.get("procedural"):
        add("procedural")
    engine = str(meta.get("render_engine") or "").lower()
    if "cycle" in engine:
        add("cycles")
    if "eevee" in engine:
        add("eevee")
    faces = int(meta.get("faces") or 0)
    if 0 < faces < 5000:
        add("low-poly")
    if faces > 200000:
        add("high-poly")
    tex = str(meta.get("texture_label") or "")
    if tex in ("2K", "4K", "8K"):
        add(tex.lower())
    if meta.get("rigged") and 0 < faces < 40000:
        add("game-ready")
    return tags[:12]


def format_polycount(n: int) -> str:
    count = max(int(n or 0), 0)
    if count >= 1_000_000:
        value = f"{count / 1_000_000:.1f}".rstrip("0").rstrip(".")
        return f"{value}M"
    if count >= 10_000:
        value = f"{count / 1000:.1f}".rstrip("0").rstrip(".")
        return f"{value}k"
    return str(count)


def listing_blurb(meta: Mapping[str, Any], title: str) -> tuple[str, str]:
    title = (title or "Untitled asset").strip()
    faces = int(meta.get("faces") or 0)
    meshes = int(meta.get("mesh_count") or 0)
    mats = int(meta.get("material_count") or 0)
    version = str(meta.get("blender_version") or "").strip()
    bits = []
    if meshes:
        bits.append(f"{meshes} mesh{'es' if meshes != 1 else ''}")
    if faces:
        bits.append(f"{format_polycount(faces)} polys")
    if meta.get("rigged"):
        bits.append("rigged")
    if meta.get("animated"):
        bits.append("animated")
    if version:
        bits.append(f"Blender {version}")
    short = f"{title} — {', '.join(bits)}." if bits else f"{title} — Blender asset."

    lines = [title, ""]
    counts = []
    if meshes:
        counts.append(f"{meshes} mesh{'es' if meshes != 1 else ''}")
    if faces:
        counts.append(f"{faces} faces")
    verts = int(meta.get("verts") or 0)
    if verts:
        counts.append(f"{verts} verts")
    if mats:
        counts.append(f"{mats} material{'s' if mats != 1 else ''}")
    if counts:
        lines.append(" · ".join(counts))
    size = str(meta.get("size_label") or "").strip()
    if size:
        lines.append(f"Size ~ {size}")
    extras = []
    tex = str(meta.get("texture_label") or "").strip()
    if tex and tex != "AUTO":
        extras.append(f"Textures {tex}")
    if meta.get("uv_unwrapped"):
        extras.append("UV unwrapped")
    if meta.get("pbr"):
        extras.append("PBR (metallic-roughness)")
    if meta.get("procedural"):
        extras.append("Procedural materials")
    if meta.get("geometry_nodes"):
        extras.append("Geometry Nodes")
    if meta.get("rigged"):
        bones = int(meta.get("bone_count") or 0)
        extras.append(f"Rigged ({bones} bones)" if bones else "Rigged")
    if meta.get("animated"):
        actions = int(meta.get("action_count") or 0)
        frames = str(meta.get("frame_range") or "").strip()
        extra = "Animated"
        if actions:
            extra += f", {actions} action{'s' if actions != 1 else ''}"
        if frames:
            extra += f", frames {frames}"
        extras.append(extra)
    if meta.get("shape_keys"):
        extras.append("Shape keys")
    if meta.get("hair"):
        extras.append("Hair / curves")
    if extras:
        lines.append(" · ".join(extras))
    engine = str(meta.get("render_engine_label") or "").strip()
    software = "Blender " + version if version else "Blender"
    if engine:
        software += f" · {engine}"
    lines.append(software)
    description = "\n".join(line for line in lines if line is not None).strip()
    return short[:500], description[:10000]


def build_listing_fields(
    *,
    title: str,
    description: str = "",
    short_description: str = "",
    price: float = 0.0,
    currency: str = "USD",
    category: str = "3d-models",
    tags: str = "blender",
    status: str = "draft",
    file_format: str = "BLEND",
    polygon_count: str = "",
    texture_resolution: str = "",
    rigged: bool = False,
    animated: bool = False,
    file_size: str = "",
    software_version: str = "",
    license: str = "CC BY 4.0",
    compatibility: Optional[Mapping[str, bool]] = None,
    specifications: Optional[Mapping[str, Any]] = None,
    render_ready: bool = False,
    pbr_workflow: str = "",
    uv_unwrapped: bool = False,
    lods: bool = False,
    target_engine: str = "",
    video_preview_url: str = "",
    pricing_type: str = "",
) -> dict[str, str]:
    """Multipart string fields the addon POST matches the website create form."""
    title = (title or "").strip() or "Untitled asset"
    description = (description or "").strip() or title
    short = (short_description or "").strip() or description[:240]
    currency = currency if currency in ("USD", "EUR") else "USD"
    category = listing_category_slug(category) if category not in PRODUCT_CATEGORIES else category
    status = status if status in ("draft", "published") else "draft"
    license_value = LICENSE_API.get(license, license) if license else "CC BY 4.0"
    if license_value not in LICENSE_API.values():
        license_value = "CC BY 4.0"
    parsed_price = float(price or 0)
    if parsed_price < 0:
        parsed_price = 0.0
    pricing = pricing_type or ("free" if parsed_price == 0 else "fixed")
    if pricing not in ("fixed", "free", "pwyw"):
        pricing = "fixed"
    compat = compatibility or {
        "blender": True,
        "maya": False,
        "max3ds": False,
        "cinema4d": False,
        "unity": False,
        "unreal": False,
    }
    specs = specifications or {}
    fields = {
        "title": title[:200],
        "description": description[:100000],
        "shortDescription": short[:500],
        "price": f"{parsed_price:g}",
        "currency": currency,
        "category": category,
        "tags": normalize_tags(tags or "blender"),
        "status": status,
        "fileFormat": (file_format or "BLEND")[:200],
        "rigged": "true" if rigged else "false",
        "animated": "true" if animated else "false",
        "license": license_value,
        "compatibility": json.dumps(dict(compat)),
        "specifications": json.dumps(dict(specs)),
        "renderReady": "true" if render_ready else "false",
        "uvUnwrapped": "true" if uv_unwrapped else "false",
        "lods": "true" if lods else "false",
        "pricingType": pricing,
        "delivery": json.dumps({"method": "instant", "time": "Immediate"}),
    }
    if polygon_count:
        fields["polygonCount"] = str(polygon_count)[:100]
    if texture_resolution in ("1K", "2K", "4K", "8K", "procedural"):
        fields["textureResolution"] = texture_resolution
    if file_size:
        fields["fileSize"] = str(file_size)[:100]
    if software_version:
        fields["softwareVersion"] = str(software_version)[:200]
    if pbr_workflow in ("metallic-roughness", "specular-glossiness"):
        fields["pbrWorkflow"] = pbr_workflow
    if target_engine:
        fields["targetEngine"] = str(target_engine)[:200]
    url = (video_preview_url or "").strip()
    if url.startswith("http://") or url.startswith("https://"):
        fields["videoPreviewUrl"] = url
    return fields


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
    if name.endswith(".png"):
        return "image/png"
    if name.endswith(".jpg") or name.endswith(".jpeg"):
        return "image/jpeg"
    if name.endswith(".webp"):
        return "image/webp"
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
