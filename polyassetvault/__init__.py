bl_info = {
    "name": "PolyAssetVault",
    "author": "Vassbrekke AS",
    "version": (0, 2, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar / Asset Shelf / Asset Browser",
    "description": "Browse, buy, import, and list 3D assets on the PolyAssetVault marketplace",
    "category": "Import-Export",
    "doc_url": "https://polyassetvault.com",
    "tracker_url": "https://polyassetvault.com",
}

if "bpy" in locals():
    import importlib

    from . import api as _api
    from . import auth as _auth
    from . import operators as _operators
    from . import prefs as _prefs
    from . import ui as _ui
    from . import assets as _assets

    importlib.reload(_api)
    importlib.reload(_auth)
    importlib.reload(_prefs)
    importlib.reload(_operators)
    importlib.reload(_ui)
    importlib.reload(_assets)

from . import assets, operators, prefs, ui


def register():
    prefs.register()
    operators.register()
    ui.register()
    assets.register()
    try:
        assets.ensure_user_library()
    except Exception:
        pass


def unregister():
    assets.unregister()
    ui.unregister()
    operators.unregister()
    prefs.unregister()
