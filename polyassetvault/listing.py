"""Listing export helpers that need Blender (bpy). Field encoding lives in api.py."""

from __future__ import annotations

import os
import shutil

import bpy

from .api import (
    category_enum_id,
    format_file_size,
    format_polycount,
    infer_category,
    infer_tags,
    is_png_file,
    listing_blurb,
    title_from_identifier,
)

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


def _texture_label(enum_id: str) -> str:
    return {"res_1K": "1K", "res_2K": "2K", "res_4K": "4K", "res_8K": "8K", "res_procedural": "procedural"}.get(
        enum_id, ""
    )


def _engine_label(engine: str) -> str:
    raw = (engine or "").upper()
    if "CYCLE" in raw:
        return "Cycles"
    if "EEVEE" in raw:
        return "EEVEE"
    if "WORKBENCH" in raw:
        return "Workbench"
    return ""


def _object_images(objects) -> list:
    images = []
    seen = set()
    for obj in objects:
        for slot in getattr(obj, "material_slots", []) or []:
            mat = getattr(slot, "material", None)
            tree = getattr(mat, "node_tree", None) if mat and getattr(mat, "use_nodes", False) else None
            if tree is None:
                continue
            for node in tree.nodes:
                image = getattr(node, "image", None)
                if image is None:
                    continue
                key = image.name
                if key in seen:
                    continue
                seen.add(key)
                images.append(image)
    return images


def _bounds_size(objects) -> tuple[float, float, float]:
    try:
        from mathutils import Vector
    except Exception:
        return (0.0, 0.0, 0.0)
    mins = [1e12, 1e12, 1e12]
    maxs = [-1e12, -1e12, -1e12]
    found = False
    for obj in objects:
        try:
            matrix = obj.matrix_world
            for corner in obj.bound_box:
                world = matrix @ Vector(corner)
                found = True
                for i in range(3):
                    mins[i] = min(mins[i], float(world[i]))
                    maxs[i] = max(maxs[i], float(world[i]))
        except Exception:
            continue
    if not found:
        return (0.0, 0.0, 0.0)
    return (maxs[0] - mins[0], maxs[1] - mins[1], maxs[2] - mins[2])


def _size_label(width: float, height: float, depth: float, scene) -> tuple[str, dict]:
    unit = "m"
    scale = 1.0
    try:
        settings = scene.unit_settings
        scale = float(getattr(settings, "scale_length", 1.0) or 1.0)
        system = str(getattr(settings, "system", "") or "")
        length = str(getattr(settings, "length_unit", "") or "")
    except Exception:
        system = ""
        length = ""
    w, h, d = width * scale, height * scale, depth * scale
    if system == "IMPERIAL":
        unit = "ft" if max(w, h, d) >= 1 else "in"
        if unit == "in":
            w, h, d = w * 12, h * 12, d * 12
    else:
        if max(w, h, d) < 0.5:
            unit = "cm"
            w, h, d = w * 100, h * 100, d * 100
        elif length == "MILLIMETERS" and max(w, h, d) < 2:
            unit = "mm"
            w, h, d = w * 1000, h * 1000, d * 1000
        else:
            unit = "m"
    if max(w, h, d) <= 0:
        return "", {}

    def pretty(value: float) -> str:
        text = f"{value:.2f}".rstrip("0").rstrip(".")
        return text or "0"

    label = f"{pretty(w)} × {pretty(h)} × {pretty(d)} {unit}"
    dims = {"width": round(w, 4), "height": round(h, 4), "depth": round(d, 4), "unit": unit}
    return label, dims


def scene_stats(context) -> dict:
    objects = listing_objects(context)
    meshes = [obj for obj in objects if getattr(obj, "type", "") == "MESH" and obj.data]
    faces = 0
    verts = 0
    uv_unwrapped = False
    shape_keys = False
    materials = set()
    for obj in meshes:
        try:
            faces += len(obj.data.polygons)
            verts += len(obj.data.vertices)
        except Exception:
            pass
        try:
            if obj.data.uv_layers:
                uv_unwrapped = True
        except Exception:
            pass
        try:
            keys = obj.data.shape_keys
            if keys and len(keys.key_blocks) > 1:
                shape_keys = True
        except Exception:
            pass
        for slot in getattr(obj, "material_slots", []) or []:
            mat = getattr(slot, "material", None)
            if mat:
                materials.add(mat.name)

    rigged = False
    animated = False
    lods = False
    geometry_nodes = False
    hair = False
    armature_count = 0
    bone_count = 0
    action_names = set()
    light_count = 0
    camera_count = 0
    names = []
    asset_description = ""
    for obj in objects:
        names.append(obj.name)
        obj_type = getattr(obj, "type", "")
        if obj_type == "ARMATURE":
            armature_count += 1
            rigged = True
            try:
                bone_count += len(obj.data.bones)
            except Exception:
                pass
        if obj_type == "LIGHT":
            light_count += 1
        if obj_type == "CAMERA":
            camera_count += 1
        if obj_type in {"CURVES", "HAIR_CURVES"}:
            hair = True
        try:
            if obj.find_armature():
                rigged = True
        except Exception:
            pass
        ad = getattr(obj, "animation_data", None)
        if ad and getattr(ad, "action", None):
            animated = True
            action_names.add(ad.action.name)
        if ad:
            try:
                if list(ad.nla_tracks):
                    animated = True
            except Exception:
                pass
        try:
            for mod in obj.modifiers:
                if mod.type == "NODES":
                    geometry_nodes = True
                if mod.type == "PARTICLE_SYSTEM":
                    hair = True
        except Exception:
            pass
        try:
            for sys in getattr(obj, "particle_systems", []) or []:
                settings = getattr(sys, "settings", None)
                if settings and str(getattr(settings, "type", "")).upper() == "HAIR":
                    hair = True
        except Exception:
            pass
        if "lod" in (obj.name or "").lower():
            lods = True
        try:
            data = obj.asset_data
            if data and not asset_description:
                asset_description = str(getattr(data, "description", "") or "")
            if data:
                for tag in getattr(data, "tags", []) or []:
                    names.append(getattr(tag, "name", "") or "")
        except Exception:
            pass
        try:
            for coll in obj.users_collection:
                names.append(coll.name)
        except Exception:
            pass

    images = _object_images(objects)
    max_dim = 0
    has_image_tex = False
    for image in images:
        has_image_tex = True
        try:
            max_dim = max(max_dim, int(image.size[0] or 0), int(image.size[1] or 0))
        except Exception:
            pass
    pbr = False
    for obj in meshes:
        for slot in getattr(obj, "material_slots", []) or []:
            mat = getattr(slot, "material", None)
            if mat and getattr(mat, "use_nodes", False):
                pbr = True
                break
        if pbr:
            break
    procedural = pbr and not has_image_tex
    tex_enum = "res_procedural" if procedural else _texture_bucket(max_dim)

    world_hdri = False
    try:
        world = context.scene.world
        tree = world.node_tree if world and world.use_nodes else None
        if tree:
            for node in tree.nodes:
                if getattr(node, "image", None) is not None:
                    world_hdri = True
    except Exception:
        pass

    engine = str(getattr(context.scene.render, "engine", "") or "")
    version = str(getattr(bpy.app, "version_string", "") or "").strip()
    selected = list(context.selected_objects or [])
    if selected:
        title_source = selected[0].name
    elif bpy.data.filepath:
        title_source = os.path.splitext(os.path.basename(bpy.data.filepath))[0]
    else:
        title_source = "Untitled asset"
    title = title_from_identifier(title_source)

    width, height, depth = _bounds_size(meshes or objects)
    size_label, dimensions = _size_label(width, height, depth, context.scene)
    frame_range = ""
    try:
        if animated:
            start = int(context.scene.frame_start)
            end = int(context.scene.frame_end)
            if end > start:
                frame_range = f"{start}–{end}"
    except Exception:
        pass

    meta = {
        "mesh_count": len(meshes),
        "faces": faces,
        "verts": verts,
        "material_count": len(materials),
        "armature_count": armature_count,
        "bone_count": bone_count,
        "light_count": light_count,
        "camera_count": camera_count,
        "rigged": rigged,
        "animated": animated,
        "action_count": len(action_names),
        "uv_unwrapped": uv_unwrapped,
        "pbr": pbr,
        "procedural": procedural,
        "geometry_nodes": geometry_nodes,
        "shape_keys": shape_keys,
        "hair": hair,
        "lods": lods,
        "world_hdri": world_hdri,
        "render_engine": engine,
        "render_engine_label": _engine_label(engine),
        "blender_version": version,
        "texture_label": _texture_label(tex_enum) or ("procedural" if procedural else ""),
        "size_label": size_label,
        "frame_range": frame_range,
    }
    category = infer_category(meta, names + [title_source, bpy.data.filepath or ""])
    tags = infer_tags(meta, names + [title_source])
    short, description = listing_blurb(meta, title)
    if asset_description and not description:
        description = asset_description
    hint_bits = []
    if faces:
        hint_bits.append(f"{format_polycount(faces)} faces")
    if len(meshes):
        hint_bits.append(f"{len(meshes)} mesh{'es' if len(meshes) != 1 else ''}")
    if meta["texture_label"]:
        hint_bits.append(meta["texture_label"])
    if meta["render_engine_label"]:
        hint_bits.append(meta["render_engine_label"])
    if rigged:
        hint_bits.append("rigged")
    if animated:
        hint_bits.append("animated")

    return {
        "title": title[:200],
        "short": short[:500],
        "description": (asset_description or description)[:10000],
        "polygon_count": str(faces) if faces else "",
        "rigged": rigged,
        "animated": animated,
        "uv_unwrapped": uv_unwrapped,
        "render_ready": pbr,
        "pbr_workflow": "metallic_roughness" if pbr else "NONE",
        "texture_resolution": tex_enum,
        "software_version": f"Blender {version}".strip(),
        "tags": ", ".join(tags),
        "file_format": "BLEND",
        "lods": lods,
        "target_engine": "Blender",
        "category": category,
        "category_enum": category_enum_id(category),
        "hint": " · ".join(hint_bits),
        "dimensions": dimensions,
        "size_label": size_label,
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
    cat = stats.get("category_enum") or ""
    if cat and (overwrite or state.listing_category == "cat_3d_models"):
        state.listing_category = cat
    if hasattr(state, "listing_hint"):
        state.listing_hint = stats.get("hint") or ""


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


def _capture_view_hd(context) -> None:
    """Match the 3D View camera, then OpenGL at scene render resolution (not viewport pixels)."""
    scene = context.scene
    view_layer = context.view_layer
    override = _view3d_override(context)
    old_camera = scene.camera
    old_active = view_layer.objects.active
    old_selected = list(context.selected_objects or [])
    cam_data = bpy.data.cameras.new("PAV_ThumbCam")
    cam_obj = bpy.data.objects.new("PAV_ThumbCam", cam_data)
    scene.collection.objects.link(cam_obj)
    try:
        scene.camera = cam_obj
        if override:
            with context.temp_override(**override):
                for obj in list(context.selected_objects or []):
                    obj.select_set(False)
                cam_obj.select_set(True)
                view_layer.objects.active = cam_obj
                bpy.ops.view3d.camera_to_view()
                bpy.ops.render.opengl(write_still=True, view_context=False)
        else:
            bpy.ops.render.opengl(write_still=True, view_context=False)
    finally:
        scene.camera = old_camera
        try:
            bpy.data.objects.remove(cam_obj, do_unlink=True)
        except Exception:
            pass
        try:
            if cam_data.users == 0:
                bpy.data.cameras.remove(cam_data)
        except Exception:
            pass
        for obj in old_selected:
            try:
                obj.select_set(True)
            except Exception:
                pass
        try:
            view_layer.objects.active = old_active
        except Exception:
            pass


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
            try:
                _capture_view_hd(context)
            except Exception:
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
