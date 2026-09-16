"""Preview icons for the N-panel (marketplace thumbnails on disk)."""

from __future__ import annotations

import os

import bpy

_pcoll = None


def register():
    global _pcoll
    _pcoll = bpy.utils.previews.new()


def unregister():
    global _pcoll
    if _pcoll is not None:
        bpy.utils.previews.remove(_pcoll)
        _pcoll = None


def icon_id(key: str, path: str) -> int:
    if not key or _pcoll is None:
        return 0
    existing = _pcoll.get(key)
    if existing is not None:
        return existing.icon_id
    if not path or not os.path.isfile(path):
        return 0
    try:
        preview = _pcoll.load(key, path, "IMAGE")
        return preview.icon_id
    except Exception:
        return 0
