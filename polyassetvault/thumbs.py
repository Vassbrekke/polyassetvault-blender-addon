"""Preview icons for the N-panel (marketplace thumbnails on disk).

``bpy.utils.previews`` is a submodule. ``import bpy`` does not attach it, so
``bpy.utils.previews.new()`` raises AttributeError on enable unless the
submodule is imported first.

Same-path recapture must drop the cached icon — Blender keeps the first
pixels if we only ``load()`` once per key.
"""

from __future__ import annotations

import os

import bpy

_pcoll = None


def _previews():
    try:
        import bpy.utils.previews as previews
    except Exception:
        return None
    return previews


def register():
    global _pcoll
    previews = _previews()
    if previews is None:
        _pcoll = None
        return
    try:
        _pcoll = previews.new()
    except Exception:
        _pcoll = None


def unregister():
    global _pcoll
    previews = _previews()
    if _pcoll is not None and previews is not None:
        try:
            previews.remove(_pcoll)
        except Exception:
            pass
    _pcoll = None


def forget(prefix: str) -> None:
    if not prefix or _pcoll is None:
        return
    try:
        names = [name for name in _pcoll.keys() if name == prefix or name.startswith(prefix + "_")]
        for name in names:
            try:
                del _pcoll[name]
            except Exception:
                pass
    except Exception:
        pass


def icon_id(key: str, path: str, rev: int = 0) -> int:
    if not key or _pcoll is None:
        return 0
    if not path or not os.path.isfile(path):
        return 0
    try:
        mtime = int(os.path.getmtime(path))
    except OSError:
        mtime = 0
    cache_key = f"{key}_{int(rev)}_{mtime}"
    try:
        existing = _pcoll.get(cache_key)
        if existing is not None:
            return int(existing.icon_id)
        forget(key)
        try:
            preview = _pcoll.load(cache_key, path, "IMAGE", True)
        except TypeError:
            preview = _pcoll.load(cache_key, path, "IMAGE")
        return int(preview.icon_id)
    except Exception:
        return 0
