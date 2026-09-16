bl_info = {
    "name": "PolyAssetVault",
    "author": "Vassbrekke AS",
    "version": (0, 1, 1),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > PolyAssetVault",
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

    importlib.reload(_api)
    importlib.reload(_auth)
    importlib.reload(_prefs)
    importlib.reload(_operators)
    importlib.reload(_ui)

from . import operators, prefs, ui


def register():
    prefs.register()
    operators.register()
    ui.register()


def unregister():
    ui.unregister()
    operators.unregister()
    prefs.unregister()
