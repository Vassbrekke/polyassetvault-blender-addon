"""PolyAssetVault addon HTTP client. Stdlib only — no bpy, so unit tests can import it."""

from __future__ import annotations

import json
import mimetypes
import os
import re
import secrets
import ssl
import stat
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from typing import Any, Iterable, Mapping, Optional

ADDON_VERSION = "0.3.7"
USER_AGENT = f"PolyAssetVault-Blender/{ADDON_VERSION}"
DEFAULT_TIMEOUT = 30
TRANSFER_TIMEOUT = 300
LIBRARY_NAME = "PolyAssetVault"
CATALOG_UUID = "7c2e9a10-4f3b-4c8d-9e21-00c0ffee0001"
PREVIEW_FILENAME = "preview.png"
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_ERROR_BYTES = 64 * 1024
MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024
MAX_PREVIEW_BYTES = 20 * 1024 * 1024
MAX_ZIP_FILES = 4096
MAX_ZIP_UNCOMPRESSED = 2 * 1024 * 1024 * 1024
MAX_PRODUCT_ID_LEN = 128
MAX_ADDON_ZIP_BYTES = 8 * 1024 * 1024
MAX_RELEASE_JSON_BYTES = 256 * 1024
ASSET_SUFFIXES = (".blend", ".zip")
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
GITHUB_REPO = "Vassbrekke/polyassetvault-blender-addon"
GITHUB_LATEST_RELEASE = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_DOWNLOAD_HOSTS = frozenset(
    {
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
    }
)
GITHUB_HOSTS = GITHUB_DOWNLOAD_HOSTS | frozenset({"api.github.com"})
_SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_MANIFEST_ID = re.compile(r'(?m)^id = "polyassetvault"\s*$')
_MANIFEST_VERSION = re.compile(r'(?m)^version = "([0-9]+\.[0-9]+\.[0-9]+)"\s*$')


def parse_semver(value: str) -> Optional[tuple[int, int, int]]:
    match = _SEMVER.fullmatch((value or "").strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def semver_text(value: str) -> str:
    parsed = parse_semver(value)
    if parsed is None:
        return ""
    return f"{parsed[0]}.{parsed[1]}.{parsed[2]}"


def is_newer_version(candidate: str, current: str) -> bool:
    left = parse_semver(candidate)
    right = parse_semver(current)
    return bool(left and right and left > right)


def official_release_zip_url(version: str) -> str:
    parsed = semver_text(version)
    if not parsed:
        raise AddonAPIError(0, "Invalid release version")
    return f"https://github.com/{GITHUB_REPO}/releases/download/v{parsed}/polyassetvault-{parsed}.zip"


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
GLB_MAGIC = b"glTF"


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


def is_glb_file(path: str) -> bool:
    """True for a glTF Binary (.glb) with a version-2 header. Used for the site 3D viewer."""
    if not path or not os.path.isfile(path):
        return False
    try:
        with open(path, "rb") as handle:
            header = handle.read(8)
        if len(header) < 8 or header[:4] != GLB_MAGIC:
            return False
        if int.from_bytes(header[4:8], "little") != 2:
            return False
        return os.path.getsize(path) >= 20
    except OSError:
        return False


def listing_file_paths(thumbnail_path: str, blend_path: str, glb_path: str = "") -> list[str]:
    """PNG first (catalog thumb), then GLB (site 3D viewer), then .blend (download)."""
    paths: list[str] = []
    if is_png_file(thumbnail_path):
        paths.append(thumbnail_path)
    if is_glb_file(glb_path):
        paths.append(glb_path)
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


def listing_price_error(price, *, stripe_connected: bool) -> str:
    """Reject paid listings unless Stripe payouts are connected. Empty string if OK."""
    try:
        parsed = float(price or 0)
    except (TypeError, ValueError):
        parsed = 0.0
    if parsed > 0 and parsed < 1:
        return "Price must be free (0) or at least 1.00."
    if parsed > 0 and not stripe_connected:
        return "Connect Stripe on the website to list a paid product. Free listings (0) are allowed."
    return ""


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
    parsed_video = urllib.parse.urlparse(url)
    if (
        parsed_video.scheme in ("http", "https")
        and parsed_video.netloc
        and not parsed_video.username
        and not parsed_video.password
    ):
        fields["videoPreviewUrl"] = url[:2000]
    return fields


class AddonAPIError(Exception):
    def __init__(self, status: int, message: str, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.payload = payload

    def __str__(self) -> str:
        return f"HTTP {self.status}: {self.message}"


def _url_port(parsed: urllib.parse.ParseResult) -> int:
    if parsed.port is not None:
        return parsed.port
    return 443 if parsed.scheme == "https" else 80


def validate_base_url(url: str) -> str:
    text = (url or "").strip()
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise AddonAPIError(0, "URL must be http(s) with a host")
    if parsed.username or parsed.password:
        raise AddonAPIError(0, "URL must not contain credentials")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise AddonAPIError(0, "URL must be http(s) with a host")
    if parsed.scheme == "http" and host not in LOOPBACK_HOSTS:
        raise AddonAPIError(0, "HTTP is only allowed for localhost")
    return text.rstrip("/")


def is_browser_url(url: str) -> bool:
    try:
        validate_base_url(url)
        return True
    except AddonAPIError:
        return False


def url_is_allowed(url: str, allowed_bases: Iterable[str]) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False
    if parsed.username or parsed.password:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return False
    for base in allowed_bases:
        try:
            allowed = urllib.parse.urlparse(validate_base_url(base))
        except AddonAPIError:
            continue
        allowed_host = (allowed.hostname or "").lower().rstrip(".")
        if (
            host == allowed_host
            and parsed.scheme == allowed.scheme
            and _url_port(parsed) == _url_port(allowed)
        ):
            return True
    return False


def same_http_origin(url_a: str, url_b: str) -> bool:
    a = urllib.parse.urlparse(url_a)
    b = urllib.parse.urlparse(url_b)
    if a.scheme not in ("http", "https") or b.scheme not in ("http", "https"):
        return False
    if a.scheme == "https" and b.scheme != "https":
        return False
    host_a = (a.hostname or "").lower().rstrip(".")
    host_b = (b.hostname or "").lower().rstrip(".")
    return bool(host_a) and host_a == host_b and _url_port(a) == _url_port(b)


class SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        current = req.get_full_url()
        resolved = urllib.parse.urljoin(current, newurl.replace(" ", "%20"))
        if not same_http_origin(current, resolved):
            raise urllib.error.URLError("blocked cross-origin redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def path_segment(value: str) -> str:
    text = str(value or "")
    if not text or len(text) > MAX_PRODUCT_ID_LEN:
        raise AddonAPIError(0, "Invalid product id")
    if "/" in text or "\\" in text or "\x00" in text or text in (".", ".."):
        raise AddonAPIError(0, "Invalid product id")
    return urllib.parse.quote(text, safe="-_.~")


def path_within(directory: str, filename: str) -> Optional[str]:
    directory = os.path.abspath(directory)
    target = os.path.abspath(os.path.join(directory, filename))
    try:
        common = os.path.commonpath([directory, target])
    except ValueError:
        return None
    if common != directory:
        return None
    return target


def safe_basename(name: str, fallback: str = "download") -> str:
    raw = urllib.parse.unquote(str(name or "")).replace("\\", "/")
    base = os.path.basename(raw).replace("\x00", "").strip()
    if os.altsep:
        base = base.replace(os.altsep, "")
    if base in ("", ".", "..") or os.sep in base or "\n" in base or "\r" in base:
        return fallback
    return base


def safe_asset_filename(name: str, fallback: str = "download.bin") -> str:
    base = safe_basename(name, "")
    lower = base.lower()
    if base and lower.endswith(ASSET_SUFFIXES):
        return base
    fb = safe_basename(fallback, "")
    if fb and fb.lower().endswith(ASSET_SUFFIXES):
        return fb
    return "download.bin"


def zip_member_relpath(name: str) -> Optional[str]:
    text = (name or "").replace("\\", "/")
    if not text or text.startswith("/") or re.match(r"^[a-zA-Z]:", text):
        return None
    parts: list[str] = []
    for part in text.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            return None
        parts.append(part)
    if not parts:
        return None
    return os.path.join(*parts)


def safe_extract_zip(
    zip_path: str,
    dest_dir: str,
    *,
    max_files: int = MAX_ZIP_FILES,
    max_uncompressed: int = MAX_ZIP_UNCOMPRESSED,
) -> str:
    dest_dir = os.path.abspath(dest_dir)
    os.makedirs(dest_dir, exist_ok=True)
    written = 0
    with zipfile.ZipFile(zip_path) as archive:
        infos = archive.infolist()
        if len(infos) > max_files:
            raise AddonAPIError(0, "Archive has too many files")
        for info in infos:
            mode = info.external_attr >> 16
            if mode and stat.S_ISLNK(mode):
                raise AddonAPIError(0, "Archive contains a symbolic link")
            rel = zip_member_relpath(info.filename)
            if rel is None:
                raise AddonAPIError(0, "Archive contains an unsafe path")
            target = path_within(dest_dir, rel)
            if target is None:
                raise AddonAPIError(0, "Archive contains an unsafe path")
            if info.is_dir() or info.filename.endswith("/"):
                os.makedirs(target, exist_ok=True)
                continue
            parent = os.path.dirname(target)
            os.makedirs(parent, exist_ok=True)
            if os.path.lexists(target):
                if os.path.islink(target) or os.path.isdir(target):
                    raise AddonAPIError(0, "Archive would overwrite a link or directory")
                os.remove(target)
            with archive.open(info, "r") as src, open(target, "wb") as out:
                while True:
                    chunk = src.read(1024 * 256)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > max_uncompressed:
                        raise AddonAPIError(0, "Archive is too large")
                    out.write(chunk)
    return dest_dir


def _read_limited(handle, limit: int, what: str) -> bytes:
    data = handle.read(limit + 1)
    if len(data) > limit:
        raise AddonAPIError(0, f"{what} too large")
    return data


def _copy_limited(src, dest, limit: int) -> int:
    total = 0
    while True:
        chunk = src.read(1024 * 256)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise AddonAPIError(0, "Download exceeds size limit")
        dest.write(chunk)
    return total


def _multipart_token(value: str) -> str:
    return str(value).replace("\r", "").replace("\n", "").replace('"', "")


def looks_like_image(path: str) -> bool:
    try:
        with open(path, "rb") as handle:
            prefix = handle.read(16)
    except OSError:
        return False
    if prefix.startswith(PNG_MAGIC) or prefix.startswith(b"\xff\xd8\xff"):
        return True
    if prefix.startswith((b"GIF87a", b"GIF89a")):
        return True
    return len(prefix) >= 12 and prefix.startswith(b"RIFF") and prefix[8:12] == b"WEBP"


def _open_replace_file(path: str):
    if os.path.lexists(path) and (os.path.islink(path) or os.path.isdir(path)):
        raise AddonAPIError(0, "Refusing to overwrite a link or directory")
    return open(path, "wb")


def _unlink_quiet(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _safe_opener() -> urllib.request.OpenerDirector:
    opener = urllib.request.OpenerDirector()
    context = ssl.create_default_context()
    for handler in (
        urllib.request.ProxyHandler(),
        urllib.request.UnknownHandler(),
        urllib.request.HTTPHandler(),
        urllib.request.HTTPDefaultErrorHandler(),
        SameOriginRedirectHandler(),
        urllib.request.HTTPSHandler(context=context),
        urllib.request.HTTPErrorProcessor(),
    ):
        opener.add_handler(handler)
    return opener


class GitHubRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        current = req.get_full_url()
        resolved = urllib.parse.urljoin(current, newurl.replace(" ", "%20"))
        parsed = urllib.parse.urlparse(resolved)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme != "https" or parsed.username or parsed.password or host not in GITHUB_HOSTS:
            raise urllib.error.URLError("blocked cross-origin redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _github_opener() -> urllib.request.OpenerDirector:
    opener = urllib.request.OpenerDirector()
    context = ssl.create_default_context()
    for handler in (
        urllib.request.ProxyHandler(),
        urllib.request.UnknownHandler(),
        urllib.request.HTTPHandler(),
        urllib.request.HTTPDefaultErrorHandler(),
        GitHubRedirectHandler(),
        urllib.request.HTTPSHandler(context=context),
        urllib.request.HTTPErrorProcessor(),
    ):
        opener.add_handler(handler)
    return opener


def parse_github_release(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AddonAPIError(0, "Invalid release metadata")
    if payload.get("draft") or payload.get("prerelease"):
        raise AddonAPIError(0, "Latest GitHub release is not a stable build")
    version = semver_text(str(payload.get("tag_name") or ""))
    if not version:
        raise AddonAPIError(0, "Invalid release version")
    expected_name = f"polyassetvault-{version}.zip"
    expected_url = official_release_zip_url(version)
    for asset in payload.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        if str(asset.get("name") or "") != expected_name:
            continue
        try:
            size = int(asset.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        if size <= 0 or size > MAX_ADDON_ZIP_BYTES:
            raise AddonAPIError(0, "Release zip is missing or too large")
        url = str(asset.get("browser_download_url") or "")
        if url != expected_url:
            raise AddonAPIError(0, "Release zip URL is not the official GitHub asset")
        return {"version": version, "url": expected_url, "size": size, "name": expected_name}
    raise AddonAPIError(0, "Release has no addon zip")


def addon_zip_is_valid(path: str, version: str) -> bool:
    expected = semver_text(version)
    if not expected or not path or not os.path.isfile(path):
        return False
    if not zipfile.is_zipfile(path):
        return False
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) > MAX_ZIP_FILES:
                return False
            for name in names:
                if zip_member_relpath(name) is None:
                    return False
            if "polyassetvault/blender_manifest.toml" not in names:
                return False
            raw = archive.read("polyassetvault/blender_manifest.toml")
            if len(raw) > 64 * 1024:
                return False
            text = raw.decode("utf-8")
    except Exception:
        return False
    if not _MANIFEST_ID.search(text):
        return False
    match = _MANIFEST_VERSION.search(text)
    return bool(match and match.group(1) == expected)


def fetch_github_latest_release() -> dict[str, Any]:
    req = urllib.request.Request(
        GITHUB_LATEST_RELEASE,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    try:
        with _github_opener().open(req, timeout=DEFAULT_TIMEOUT) as resp:
            final = urllib.parse.urlparse(resp.geturl())
            host = (final.hostname or "").lower().rstrip(".")
            if final.scheme != "https" or host != "api.github.com":
                raise AddonAPIError(0, "Unexpected update server")
            raw = _read_limited(resp, MAX_RELEASE_JSON_BYTES, "Release metadata")
    except AddonAPIError:
        raise
    except urllib.error.HTTPError as exc:
        raise AddonAPIError(exc.code, "Could not read GitHub Releases") from exc
    except Exception as exc:
        raise AddonAPIError(0, "Could not reach GitHub Releases") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AddonAPIError(0, "Invalid release metadata") from exc
    return parse_github_release(payload)


def download_github_release_zip(version: str, dest_path: str) -> str:
    url = official_release_zip_url(version)
    dest_path = os.path.abspath(dest_path)
    directory = os.path.dirname(dest_path) or "."
    os.makedirs(directory, exist_ok=True)
    if path_within(directory, os.path.basename(dest_path)) != dest_path:
        raise AddonAPIError(0, "Invalid download path")
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/octet-stream", "User-Agent": USER_AGENT},
        method="GET",
    )
    try:
        with _github_opener().open(req, timeout=TRANSFER_TIMEOUT) as resp:
            final = urllib.parse.urlparse(resp.geturl())
            host = (final.hostname or "").lower().rstrip(".")
            if final.scheme != "https" or host not in GITHUB_DOWNLOAD_HOSTS:
                raise AddonAPIError(0, "Blocked request to an untrusted URL")
            with _open_replace_file(dest_path) as handle:
                _copy_limited(resp, handle, MAX_ADDON_ZIP_BYTES)
    except AddonAPIError:
        _unlink_quiet(dest_path)
        raise
    except urllib.error.HTTPError as exc:
        _unlink_quiet(dest_path)
        raise AddonAPIError(exc.code, "Could not download the update zip") from exc
    except Exception as exc:
        _unlink_quiet(dest_path)
        raise AddonAPIError(0, "Could not download the update zip") from exc
    if not addon_zip_is_valid(dest_path, version):
        _unlink_quiet(dest_path)
        raise AddonAPIError(0, "Downloaded file is not the official addon zip")
    return dest_path


def join_url(base: str, path: str) -> str:
    base = (base or "").rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return base + path


def absolute_url(base: str, maybe_relative: Optional[str]) -> Optional[str]:
    if not maybe_relative:
        return None
    text = maybe_relative.strip()
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme:
        try:
            allowed = [validate_base_url(base)]
        except AddonAPIError:
            return None
        if not url_is_allowed(text, allowed):
            return None
        return text
    path = text if text.startswith("/") else "/" + text
    return join_url(base, path)


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
        field = _multipart_token(key)
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            f'Content-Disposition: form-data; name="{field}"\r\n\r\n'.encode("utf-8")
        )
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")
    for field_name, filename, content, content_type in files:
        safe_name = _multipart_token(safe_basename(filename, "upload.bin"))
        ctype = _multipart_token(content_type or "application/octet-stream")
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            (
                f'Content-Disposition: form-data; name="{_multipart_token(field_name)}"; '
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
    if name.endswith(".glb"):
        return "model/gltf-binary"
    if name.endswith(".gltf"):
        return "model/gltf+json"
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
        return safe_asset_filename(fallback, "download.bin")
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', header, re.I)
    if not match:
        match = re.search(r'filename="([^"]+)"', header, re.I)
    if match:
        return safe_asset_filename(match.group(1).strip(), fallback)
    return safe_asset_filename(fallback, "download.bin")


class AddonClient:
    def __init__(
        self,
        api_base: str,
        token: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT,
        opener: Optional[urllib.request.OpenerDirector] = None,
        site_url: Optional[str] = None,
    ):
        self.api_base = validate_base_url(api_base)
        self.token = token or ""
        self.timeout = timeout
        self._allowed_bases = [self.api_base]
        if site_url:
            try:
                self._allowed_bases.append(validate_base_url(site_url))
            except AddonAPIError:
                pass
        self._opener = opener or _safe_opener()

    def _assert_url(self, url: str) -> None:
        if not url_is_allowed(url, self._allowed_bases):
            raise AddonAPIError(0, "Blocked request to an untrusted URL")

    def _headers(
        self,
        extra: Optional[Mapping[str, str]] = None,
        *,
        url: str = "",
        send_auth: bool = True,
    ) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        if send_auth and self.token and (not url or same_http_origin(url, self.api_base)):
            headers["X-Addon-Token"] = self.token
        if extra:
            headers.update(extra)
        return headers

    def _open(self, req: urllib.request.Request, timeout: Optional[int] = None):
        self._assert_url(req.get_full_url())
        try:
            return self._opener.open(req, timeout=timeout if timeout is not None else self.timeout)
        except urllib.error.HTTPError as exc:
            payload = None
            message = exc.reason or "Request failed"
            try:
                raw = exc.read(MAX_ERROR_BYTES)
                if raw:
                    payload = json.loads(raw.decode("utf-8"))
                    if isinstance(payload, dict):
                        message = (
                            payload.get("message")
                            or payload.get("error")
                            or message
                        )
                    else:
                        payload = None
            except Exception:
                payload = None
            raise AddonAPIError(exc.code, str(message), payload) from exc
        except urllib.error.URLError as exc:
            raise AddonAPIError(0, f"Network error: {exc.reason}") from exc

    def _load_json(self, raw: bytes) -> Any:
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AddonAPIError(0, "Invalid JSON response") from exc

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
        if not path.startswith("/") or path.startswith("//"):
            raise AddonAPIError(0, "Invalid API path")
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
            headers=self._headers(extra, url=url),
            method=method.upper(),
        )
        with self._open(req, timeout=timeout) as resp:
            raw = _read_limited(resp, MAX_JSON_BYTES, "Response")
            return self._load_json(raw)

    def request_multipart(
        self,
        method: str,
        path: str,
        fields: Mapping[str, str],
        files: Iterable[tuple[str, str, bytes, str]],
        timeout: int = TRANSFER_TIMEOUT,
    ) -> Any:
        if not path.startswith("/") or path.startswith("//"):
            raise AddonAPIError(0, "Invalid API path")
        body, content_type = encode_multipart(fields, files)
        url = join_url(self.api_base, path)
        req = urllib.request.Request(
            url,
            data=body,
            headers=self._headers({"Content-Type": content_type}, url=url),
            method=method.upper(),
        )
        with self._open(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            raw = _read_limited(resp, MAX_JSON_BYTES, "Response")
            if not raw:
                return {"_http_status": status}
            payload = self._load_json(raw)
            if isinstance(payload, dict):
                payload["_http_status"] = status
            return payload

    def download_file(self, path: str, dest_path: str, timeout: int = TRANSFER_TIMEOUT) -> str:
        if not path.startswith("/") or path.startswith("//"):
            raise AddonAPIError(0, "Invalid API path")
        url = join_url(self.api_base, path)
        req = urllib.request.Request(url, headers=self._headers(url=url), method="GET")
        directory = os.path.dirname(os.path.abspath(dest_path)) or "."
        os.makedirs(directory, exist_ok=True)
        final_path = None
        try:
            with self._open(req, timeout=timeout) as resp:
                filename = _filename_from_disposition(
                    resp.headers.get("Content-Disposition"),
                    os.path.basename(dest_path) or "download.bin",
                )
                final_path = path_within(directory, filename)
                if final_path is None:
                    raise AddonAPIError(0, "Invalid download filename")
                with _open_replace_file(final_path) as handle:
                    _copy_limited(resp, handle, MAX_DOWNLOAD_BYTES)
        except Exception:
            if final_path:
                _unlink_quiet(final_path)
            raise
        return final_path

    def download_to(self, url_or_path: str, dest_path: str, timeout: int = DEFAULT_TIMEOUT) -> str:
        url = (url_or_path or "").strip()
        if url.startswith("/"):
            url = join_url(self.api_base, url)
        if not url:
            raise AddonAPIError(0, "No download URL")
        self._assert_url(url)
        dest_path = os.path.abspath(dest_path)
        directory = os.path.dirname(dest_path) or "."
        os.makedirs(directory, exist_ok=True)
        if path_within(directory, os.path.basename(dest_path)) != dest_path:
            raise AddonAPIError(0, "Invalid download path")
        req = urllib.request.Request(
            url, headers=self._headers(url=url, send_auth=False), method="GET"
        )
        try:
            with self._open(req, timeout=timeout) as resp:
                with _open_replace_file(dest_path) as handle:
                    _copy_limited(resp, handle, MAX_PREVIEW_BYTES)
            if not looks_like_image(dest_path):
                raise AddonAPIError(0, "Preview was not a valid image")
        except Exception:
            _unlink_quiet(dest_path)
            raise
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
        return self.request_json("GET", f"/api/addon/products/{path_segment(product_id)}")

    def purchases(self) -> dict:
        return self.request_json("GET", "/api/addon/purchases")

    def my_products(self, *, status: str = "", page: int = 1, limit: int = 50) -> dict:
        return self.request_json(
            "GET",
            "/api/addon/my-products",
            query={"status": status, "page": page, "limit": limit},
        )

    def download_product(self, product_id: str, dest_path: str) -> str:
        return self.download_file(
            f"/api/addon/products/{path_segment(product_id)}/download", dest_path
        )

    def _upload_files(self, file_paths: Iterable[str]) -> list[tuple[str, str, bytes, str]]:
        files: list[tuple[str, str, bytes, str]] = []
        for path in file_paths:
            name = os.path.basename(path)
            ctype = file_content_type(name)
            try:
                size = os.path.getsize(path)
            except OSError as exc:
                raise AddonAPIError(0, "Could not read upload") from exc
            if size > MAX_DOWNLOAD_BYTES:
                raise AddonAPIError(0, "File too large to upload")
            with open(path, "rb") as handle:
                files.append(("files", name, handle.read(), ctype))
        return files

    def create_product(
        self,
        fields: Mapping[str, str],
        file_paths: Iterable[str],
    ) -> dict:
        return self.request_multipart("POST", "/api/addon/products", fields, self._upload_files(file_paths))

    def update_product(
        self,
        product_id: str,
        fields: Mapping[str, str],
        file_paths: Iterable[str] = (),
    ) -> dict:
        return self.request_multipart(
            "PUT",
            f"/api/addon/products/{path_segment(product_id)}",
            fields,
            self._upload_files(file_paths),
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
        if os.path.islink(path) or not os.path.isfile(path):
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
    return join_url(validate_base_url(site_url), f"/product/{path_segment(product_id)}")


def login_page_url(site_url: str, port: int, state: str) -> str:
    if not isinstance(port, int) or not (49152 <= port <= 65535):
        raise AddonAPIError(0, "Invalid callback port")
    text = str(state or "")
    if not text or len(text) > 128:
        raise AddonAPIError(0, "Invalid login state")
    query = urllib.parse.urlencode({"port": port, "state": text})
    return join_url(validate_base_url(site_url), f"/addon-login?{query}")
