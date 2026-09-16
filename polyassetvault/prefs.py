"""Addon preferences — site URL, API base, device token, download folder."""

from __future__ import annotations

import bpy
from bpy.props import StringProperty
from bpy.types import AddonPreferences

from .api import ADDON_VERSION

ADDON_ID = __package__


class PAV_AddonPreferences(AddonPreferences):
    bl_idname = ADDON_ID

    site_url: StringProperty(
        name="Site URL",
        description="PolyAssetVault website used for sign-in and checkout",
        default="https://polyassetvault.com",
    )
    api_base_url: StringProperty(
        name="API base URL",
        description="Backend origin. Production is the site URL. Local dev is http://localhost:5000",
        default="https://polyassetvault.com",
    )
    device_token: StringProperty(
        name="Device token",
        description="30-day addon device token. Issued after browser sign-in. Never share this.",
        default="",
        subtype="PASSWORD",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    # Persisted copy — SKIP_SAVE on device_token would wipe login every restart.
    # Blender still encrypts addon prefs in userconfig; we keep a dedicated field.
    stored_token: StringProperty(
        name="Stored token",
        default="",
        options={"HIDDEN"},
        subtype="PASSWORD",
    )
    download_dir: StringProperty(
        name="Download folder",
        description="Where purchased .blend / .zip files are saved before import",
        default="//polyassetvault_library/",
        subtype="DIR_PATH",
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "site_url")
        layout.prop(self, "api_base_url")
        layout.prop(self, "download_dir")
        row = layout.row()
        row.label(text=f"Addon version {ADDON_VERSION}")
        if self.get_token():
            row.label(text="Signed in", icon="USER")
        else:
            row.label(text="Not signed in", icon="QUESTION")

    def get_token(self) -> str:
        return (self.stored_token or self.device_token or "").strip()

    def set_token(self, token: str) -> None:
        self.stored_token = token or ""
        self.device_token = token or ""

    def clear_token(self) -> None:
        self.set_token("")


def get_prefs(context=None) -> PAV_AddonPreferences:
    ctx = context or bpy.context
    return ctx.preferences.addons[ADDON_ID].preferences


def register():
    bpy.utils.register_class(PAV_AddonPreferences)


def unregister():
    bpy.utils.unregister_class(PAV_AddonPreferences)
