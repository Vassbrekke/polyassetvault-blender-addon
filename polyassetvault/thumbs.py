"""Preview icons for the N-panel (marketplace thumbnails on disk).

``bpy.utils.previews`` is a submodule. ``import bpy`` does not attach it, so
``bpy.utils.previews.new()`` raises AttributeError on enable unless the
submodule is imported first.
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


def icon_id(key: str, path: str) -> int:
    if not key or _pcoll is None:
        return 0
    try:
        existing = _pcoll.get(key)
        if existing is not None:
            return int(existing.icon_id)
        if not path or not os.path.isfile(path):
            return 0
        preview = _pcoll.load(key, path, "IMAGE")
        return int(preview.icon_id)
    except Exception:
        return 0
