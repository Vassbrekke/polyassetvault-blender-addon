"""Listing export helpers that need Blender (bpy). Field encoding lives in api.py."""

from __future__ import annotations

import os
import shutil

import bpy

from .api import format_file_size, is_png_file

THUMB_NAME = "thumbnail.png"


def thumb_cache_path(context) -> str:
    folder = os.path.join(tempfile_fallback(), "_listing")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, THUMB_NAME)


def tempfile_fallback() -> str:
    return os.path.join(os.path.expanduser("~"), ".cache", "polyassetvault")


def listing_objects(context):
    state = context.window_manager.pav
    selected = list(context.selected_objects or [])
    if state.listing_scope == "SELECTED" and selected:
        return selected
    scene = context.scene
    return list(getattr(scene, "objects", []) or [])


def _texture_bucket(max_dim: int) -> str:
    if max_dim >= 7000:
        return "res_8K"
    if max_dim >= 3000:
        return "res_4K"
    if max_dim >= 1500:
        return "res_2K"
    if max_dim >= 700:
        return "res_1K"
    return "AUTO"


def scene_stats(context) -> dict:
    objects = listing_objects(context)
    meshes = [obj for obj in objects if getattr(obj, "type", "") == "MESH" and obj.data]
    faces = 0
    uv_unwrapped = False
    for obj in meshes:
        try:
            faces += len(obj.data.polygons)
        except Exception:
            pass
        try:
            if obj.data.uv_layers:
                uv_unwrapped = True
        except Exception:
            pass

    rigged = False
    animated = False
    lods = False
    for obj in objects:
        if obj.type == "ARMATURE":
            rigged = True
        try:
            if obj.find_armature():
                rigged = True
        except Exception:
            pass
        ad = getattr(obj, "animation_data", None)
        if ad and (getattr(ad, "action", None) or list(getattr(ad, "nla_tracks", []) or [])):
            animated = True
        name = (obj.name or "").lower()
        if "lod" in name:
            lods = True

    max_dim = 0
    for image in bpy.data.images:
        try:
            max_dim = max(max_dim, int(image.size[0] or 0), int(image.size[1] or 0))
        except Exception:
            pass

    pbr = False
    for mat in bpy.data.materials:
        if mat and getattr(mat, "use_nodes", False):
            pbr = True
            break

    version = str(getattr(bpy.app, "version_string", "") or "").strip()
    selected = list(context.selected_objects or [])
    if selected:
        title = selected[0].name
    elif bpy.data.filepath:
        title = os.path.splitext(os.path.basename(bpy.data.filepath))[0]
    else:
        title = "Untitled asset"

    tags = ["blender", "3d"]
    if rigged:
        tags.append("rigged")
    if animated:
        tags.append("animated")
    if pbr:
        tags.append("pbr")

    lines = [
        title,
        "",
        f"Blender {version} .blend asset.".strip(),
        f"Polygons: {faces}." if faces else "",
        "Rigged." if rigged else "",
        "Animated." if animated else "",
        "PBR materials." if pbr else "",
        "UV unwrapped." if uv_unwrapped else "",
    ]
    description = "\n".join(line for line in lines if line is not None).strip()
    short = f"{title} — Blender {version}".replace(" — Blender ", " — Blender ").strip(" —")
    if version:
        short = f"{title} — Blender {version}"
    else:
        short = title

    return {
        "title": title[:200],
        "short": short[:500],
        "description": description[:10000],
        "polygon_count": str(faces) if faces else "",
        "rigged": rigged,
        "animated": animated,
        "uv_unwrapped": uv_unwrapped,
        "render_ready": pbr,
        "pbr_workflow": "metallic_roughness" if pbr else "NONE",
        "texture_resolution": _texture_bucket(max_dim),
        "software_version": f"Blender {version}".strip(),
        "tags": ", ".join(tags),
        "file_format": "BLEND",
        "lods": lods,
        "target_engine": "Blender",
    }


def apply_stats(state, stats: dict, *, overwrite: bool = False) -> None:
    if overwrite or not (state.listing_title or "").strip():
        state.listing_title = stats.get("title") or state.listing_title
    if overwrite or not (state.listing_description or "").strip():
        state.listing_description = stats.get("description") or state.listing_description
    if overwrite or not (state.listing_short or "").strip():
        state.listing_short = stats.get("short") or state.listing_short
    tags = (state.listing_tags or "").strip()
    if overwrite or not tags or tags == "blender":
        state.listing_tags = stats.get("tags") or "blender"
    state.listing_polygon = stats.get("polygon_count") or state.listing_polygon
    state.listing_rigged = bool(stats.get("rigged"))
    state.listing_animated = bool(stats.get("animated"))
    state.listing_uv = bool(stats.get("uv_unwrapped"))
    state.listing_render_ready = bool(stats.get("render_ready"))
    state.listing_lods = bool(stats.get("lods"))
    tex = stats.get("texture_resolution") or "AUTO"
    if tex in ("AUTO", "res_1K", "res_2K", "res_4K", "res_8K", "res_procedural"):
        state.listing_texture = tex
    pbr = stats.get("pbr_workflow") or "NONE"
    if pbr in ("NONE", "metallic_roughness", "specular_glossiness"):
        state.listing_pbr = pbr
    if overwrite or not (state.listing_engine or "").strip():
        state.listing_engine = stats.get("target_engine") or state.listing_engine


def _view3d_override(context):
    window = context.window
    screen = context.screen
    area = context.area if context.area and context.area.type == "VIEW_3D" else None
    if area is None and screen:
        area = next((item for item in screen.areas if item.type == "VIEW_3D"), None)
    if area is None:
        return None
    region = next((item for item in area.regions if item.type == "WINDOW"), None)
    space = area.spaces.active if area.spaces else None
    return {
        "window": window,
        "screen": screen,
        "area": area,
        "region": region,
        "space_data": space,
    }


def _save_render_result(path: str) -> bool:
    image = bpy.data.images.get("Render Result")
    if image is None:
        return False
    try:
        image.save_render(filepath=path)
    except Exception:
        return False
    return is_png_file(path)


def _resolve_written_png(dest: str) -> str:
    if is_png_file(dest):
        return dest
    folder = os.path.dirname(dest)
    stem = os.path.splitext(os.path.basename(dest))[0]
    if not folder or not os.path.isdir(folder):
        return ""
    try:
        names = os.listdir(folder)
    except OSError:
        return ""
    for name in sorted(names, reverse=True):
        path = os.path.join(folder, name)
        if name.startswith(stem) and is_png_file(path):
            return path
    return ""


def _copy_as_png(src: str, dest: str) -> bool:
    if is_png_file(src):
        if os.path.abspath(src) != os.path.abspath(dest):
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(src, dest)
        return is_png_file(dest)
    try:
        image = bpy.data.images.load(src, check_existing=True)
        image.file_format = "PNG"
        image.save_render(filepath=dest)
        return is_png_file(dest)
    except Exception:
        return False


def write_thumbnail(context, dest: str, source: str = "VIEWPORT", custom: str = "") -> str:
    """Write a PNG to dest. Returns the path on success, else empty string."""
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    scene = context.scene
    render = scene.render
    old_path = render.filepath
    old_format = render.image_settings.file_format
    old_x = render.resolution_x
    old_y = render.resolution_y
    old_pct = render.resolution_percentage
    old_ext = render.use_file_extension
    try:
        if source == "FILE" and custom:
            if _copy_as_png(custom, dest):
                return dest
        render.filepath = dest
        render.image_settings.file_format = "PNG"
        render.resolution_x = 1024
        render.resolution_y = 1024
        render.resolution_percentage = 100
        render.use_file_extension = False
        if source == "CAMERA":
            try:
                bpy.ops.render.render(write_still=True)
            except Exception:
                pass
        else:
            override = _view3d_override(context)
            try:
                if override:
                    with context.temp_override(**override):
                        bpy.ops.render.opengl(write_still=True, view_context=True)
                else:
                    bpy.ops.render.opengl(write_still=True, view_context=True)
            except Exception:
                try:
                    bpy.ops.render.opengl(write_still=True)
                except Exception:
                    pass
        if _save_render_result(dest):
            return dest
        found = _resolve_written_png(dest)
        if found:
            if os.path.abspath(found) != os.path.abspath(dest):
                shutil.copy2(found, dest)
            if is_png_file(dest):
                return dest
        if custom and _copy_as_png(custom, dest):
            return dest
    finally:
        render.filepath = old_path
        render.image_settings.file_format = old_format
        render.resolution_x = old_x
        render.resolution_y = old_y
        render.resolution_percentage = old_pct
        render.use_file_extension = old_ext
    return dest if is_png_file(dest) else ""


def file_size_label(path: str) -> str:
    try:
        return format_file_size(os.path.getsize(path))
    except OSError:
        return ""
