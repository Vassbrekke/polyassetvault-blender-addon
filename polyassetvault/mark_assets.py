"""Run inside background Blender: mark objects/collections as assets and save.

Invoked as: blender --background file.blend --python mark_assets.py
Env: PAV_TITLE, PAV_AUTHOR, PAV_CATALOG_ID
"""

import os
import bpy

TITLE = os.environ.get("PAV_TITLE", "")
AUTHOR = os.environ.get("PAV_AUTHOR", "")
CATALOG = os.environ.get("PAV_CATALOG_ID", "")

SKIP_OBJECT_TYPES = {"CAMERA", "LIGHT", "SPEAKER", "LATTICE"}


def _apply_meta(id_block) -> None:
    data = getattr(id_block, "asset_data", None)
    if data is None:
        return
    if TITLE:
        try:
            data.description = TITLE[:255]
        except Exception:
            pass
    if AUTHOR:
        try:
            data.author = AUTHOR[:64]
        except Exception:
            pass
    if CATALOG:
        try:
            data.catalog_id = CATALOG
        except Exception:
            pass


def _mark(id_block) -> bool:
    try:
        id_block.asset_mark()
    except Exception:
        return False
    _apply_meta(id_block)
    return True


marked = 0
for coll in list(bpy.data.collections):
    if coll.name in {"Scene Collection", "Master Collection"}:
        continue
    if _mark(coll):
        marked += 1

if marked == 0:
    for obj in list(bpy.data.objects):
        if obj.type in SKIP_OBJECT_TYPES:
            continue
        if _mark(obj):
            marked += 1

if marked == 0:
    for obj in list(bpy.data.objects):
        if _mark(obj):
            marked += 1

bpy.ops.wm.save_mainfile()
print(f"PAV_MARKED={marked}")
