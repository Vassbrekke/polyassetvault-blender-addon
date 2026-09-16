"""Register purchased files as a native Blender asset library.

Stdlib helpers live in api.py so tests can import them. bpy is imported
here only; mark_assets.py is a standalone script for background Blender.
"""

from __future__ import annotations

import os
import subprocess

import bpy

from .api import CATALOG_UUID, LIBRARY_NAME, catalog_definition_text, find_cached_asset
from .prefs import get_prefs

CATALOG_FILENAME = "blender_assets.cats.txt"
INDEX_SUFFIX = ".pavindex"


def library_root(context=None) -> str:
    prefs = get_prefs(context)
    raw = (prefs.download_dir or "").strip()
    defaultish = raw in {"", "//polyassetvault_library/", "//polyassetvault_library"}
    if defaultish:
        try:
            root = bpy.utils.user_resource("DATAFILES", path="polyassetvault/library")
        except Exception:
            root = ""
        if not root:
            root = os.path.join(os.path.expanduser("~"), "PolyAssetVaultLibrary")
        os.makedirs(root, exist_ok=True)
        return root
    if raw.startswith("//"):
        return bpy.path.abspath(raw)
    path = os.path.abspath(os.path.expanduser(raw))
    os.makedirs(path, exist_ok=True)
    return path


def ensure_catalog_file(root: str) -> str:
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, CATALOG_FILENAME)
    expected = catalog_definition_text()
    current = ""
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                current = handle.read()
        except OSError:
            current = ""
    if current != expected:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(expected)
    return path


def ensure_user_library(context=None) -> str:
    ctx = context or bpy.context
    root = library_root(ctx)
    ensure_catalog_file(root)
    libs = ctx.preferences.filepaths.asset_libraries
    norm = os.path.normpath(root)
    for lib in libs:
        lib_path = os.path.normpath(bpy.path.abspath(lib.path) if lib.path else "")
        if lib.name == LIBRARY_NAME or lib_path == norm:
            lib.name = LIBRARY_NAME
            lib.path = root
            _set_import_method(lib)
            return root
    lib = None
    if hasattr(libs, "new"):
        try:
            lib = libs.new(name=LIBRARY_NAME)
            lib.path = root
        except Exception:
            lib = None
    if lib is None:
        bpy.ops.preferences.asset_library_add()
        lib = libs[-1]
        lib.name = LIBRARY_NAME
        lib.path = root
    _set_import_method(lib)
    try:
        bpy.ops.wm.save_userpref()
    except Exception:
        pass
    return root


def _set_import_method(lib) -> None:
    if not hasattr(lib, "import_method"):
        return
    for value in ("APPEND", "APPEND_REUSE", "PACK"):
        try:
            lib.import_method = value
            return
        except (TypeError, ValueError):
            continue


def refresh_asset_ui(context=None) -> None:
    ctx = context or bpy.context
    try:
        bpy.ops.asset.library_refresh()
    except Exception:
        pass
    for window in ctx.window_manager.windows:
        for area in window.screen.areas:
            if area.type in {"VIEW_3D", "FILE_BROWSER"}:
                area.tag_redraw()


def index_stamp(path: str) -> str:
    return path + INDEX_SUFFIX


def is_indexed(path: str) -> bool:
    return os.path.isfile(index_stamp(path))


def mark_stamp(path: str) -> None:
    try:
        with open(index_stamp(path), "w", encoding="utf-8") as handle:
            handle.write("ok\n")
    except OSError:
        pass


def mark_blend_command(blender_bin: str, script: str, filepath: str) -> list[str]:
    return [
        blender_bin,
        "--factory-startup",
        "--background",
        filepath,
        "--python",
        script,
    ]


def run_mark_blend(
    blender_bin: str,
    script: str,
    filepath: str,
    title: str = "",
    author: str = "",
    timeout: int = 90,
) -> bool:
    if not filepath.lower().endswith(".blend") or not os.path.isfile(filepath):
        return False
    if is_indexed(filepath):
        return True
    if not blender_bin or not os.path.isfile(blender_bin) or not os.path.isfile(script):
        return False
    env = os.environ.copy()
    env["PAV_TITLE"] = title or ""
    env["PAV_AUTHOR"] = author or ""
    env["PAV_CATALOG_ID"] = CATALOG_UUID
    try:
        result = subprocess.run(
            mark_blend_command(blender_bin, script, filepath),
            env=env,
            timeout=timeout,
            capture_output=True,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    mark_stamp(filepath)
    return True


def mark_blend_file(filepath: str, title: str = "", author: str = "") -> bool:
    blender = getattr(bpy.app, "binary_path", "") or ""
    script = os.path.join(os.path.dirname(__file__), "mark_assets.py")
    return run_mark_blend(blender, script, filepath, title=title, author=author)


def index_local_file(filepath: str, title: str = "", author: str = "") -> int:
    """Mark .blend (or .blend files inside a .zip extract) as assets. Returns count."""
    if not filepath or not os.path.isfile(filepath):
        return 0
    lower = filepath.lower()
    marked = 0
    if lower.endswith(".blend"):
        if mark_blend_file(filepath, title, author):
            marked += 1
        return marked
    if lower.endswith(".zip"):
        extract_dir = filepath + "_extracted"
        if os.path.isdir(extract_dir):
            for root, _dirs, files in os.walk(extract_dir):
                for name in files:
                    if name.lower().endswith(".blend"):
                        if mark_blend_file(os.path.join(root, name), title, author):
                            marked += 1
    return marked


def show_asset_shelf(context) -> int:
    shown = 0
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            space = area.spaces.active
            if hasattr(space, "show_region_asset_shelf"):
                space.show_region_asset_shelf = True
                shown += 1
            area.tag_redraw()
    return shown


def open_asset_browser_area(context) -> bool:
    screen = context.screen
    preferred = ("TEXT_EDITOR", "CONSOLE", "INFO", "NODE_EDITOR")
    for want in preferred:
        for area in screen.areas:
            if area.type == want or area.ui_type == want:
                area.ui_type = "ASSETS"
                return True
    for area in screen.areas:
        if area.type not in {"VIEW_3D", "PROPERTIES", "OUTLINER", "STATUSBAR"}:
            area.ui_type = "ASSETS"
            return True
    return False


class VIEW3D_AST_polyassetvault(bpy.types.AssetShelf):
    bl_idname = "VIEW3D_AST_polyassetvault"
    bl_label = "PolyAssetVault"
    bl_space_type = "VIEW_3D"
    bl_options = {"DEFAULT_VISIBLE", "STORE_ENABLED_CATALOGS_IN_PREFERENCES"}
    bl_default_preview_size = 96

    @classmethod
    def poll(cls, context):
        return context.mode in {"OBJECT", "EDIT_MESH", "POSE"}

    @classmethod
    def asset_poll(cls, asset):
        id_type = getattr(asset, "id_type", "")
        if id_type not in {"OBJECT", "COLLECTION"}:
            return False
        try:
            root = os.path.normpath(library_root())
        except Exception:
            return True
        lib_path = os.path.normpath(getattr(asset, "full_library_path", "") or getattr(asset, "full_path", "") or "")
        if not lib_path:
            return True
        return lib_path == root or lib_path.startswith(root + os.sep)


def register():
    bpy.utils.register_class(VIEW3D_AST_polyassetvault)


def unregister():
    bpy.utils.unregister_class(VIEW3D_AST_polyassetvault)
