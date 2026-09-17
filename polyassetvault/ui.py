"""N-panel: Account, Browse, Library, List."""

from __future__ import annotations

import bpy
from bpy.types import Panel

from .prefs import get_prefs


class PAV_PT_main(Panel):
    bl_label = "PolyAssetVault"
    bl_idname = "PAV_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "PolyAssetVault"

    def draw(self, context):
        layout = self.layout
        state = context.window_manager.pav
        prefs = get_prefs(context)
        signed_in = bool(prefs.get_token())

        layout.row().prop(state, "tab", expand=True)
        if state.status_message:
            layout.label(text=state.status_message, icon="INFO")

        if state.tab == "ACCOUNT":
            self._draw_account(layout, context, state, signed_in)
        elif state.tab == "BROWSE":
            self._draw_browse(layout, context, signed_in)
        elif state.tab == "LIBRARY":
            self._draw_library(layout, context, signed_in)
        else:
            self._draw_list(layout, context, signed_in)

    def _draw_account(self, layout, context, state, signed_in):
        box = layout.box()
        if signed_in:
            box.label(text=state.account_name or "Signed in", icon="USER")
            if state.account_type:
                box.label(text=f"Role: {state.account_type}")
            box.label(
                text="Payouts connected" if state.stripe_connected else "Connect Stripe on the website to sell"
            )
            row = box.row(align=True)
            row.operator("pav.refresh_account", icon="FILE_REFRESH")
            row.operator("pav.logout", icon="QUIT")
        else:
            box.label(text="Not signed in")
            box.operator("pav.login", icon="URL", text="Sign in with browser")
        layout.prop(get_prefs(context), "download_dir")
        row = layout.row(align=True)
        row.operator("pav.save_prefs", icon="FILE_TICK")
        row.operator("pav.open_prefs", icon="PREFERENCES", text="All settings")

    def _draw_browse(self, layout, context, signed_in):
        if not signed_in:
            layout.label(text="Sign in on the Account tab first.")
            return
        state = context.window_manager.pav
        col = layout.column(align=True)
        col.prop(state, "search", text="", icon="VIEWZOOM")
        col.prop(state, "category", text="")
        col.operator("pav.browse", icon="VIEWZOOM")
        layout.template_list(
            "PAV_UL_products",
            "browse",
            context.window_manager,
            "pav_browse",
            state,
            "browse_index",
            rows=8,
        )
        item = context.window_manager.pav_browse[state.browse_index] if context.window_manager.pav_browse else None
        if item:
            from . import thumbs
            from .operators import _preview_path

            icon_value = thumbs.icon_id(item.product_id, _preview_path(context, item.product_id))
            box = layout.box()
            if icon_value:
                box.template_icon(icon_value=icon_value, scale=6.0)
            box.label(text=item.title)
            if item.short_description:
                box.label(text=item.short_description)
            row = box.row(align=True)
            if item.owned:
                op = row.operator("pav.drag_import", text="Drag into scene", icon="IMPORT")
                op.product_id = item.product_id
                op.title = item.title
            else:
                op = row.operator("pav.buy", icon="URL")
                op.source = "BROWSE"

    def _draw_library(self, layout, context, signed_in):
        if not signed_in:
            layout.label(text="Sign in on the Account tab first.")
            return
        state = context.window_manager.pav
        layout.label(text="Drag a purchased row into the 3D view, or sync to the Asset Browser.")
        layout.prop(state, "import_mode", expand=True)
        row = layout.row(align=True)
        row.operator("pav.refresh_library", icon="FILE_REFRESH")
        row.operator("pav.sync_asset_browser", icon="ASSET_MANAGER")
        row = layout.row(align=True)
        row.operator("pav.show_asset_shelf", icon="DOWNARROW_HLT")
        row.operator("pav.open_asset_browser", icon="WINDOW")
        layout.template_list(
            "PAV_UL_products",
            "library",
            context.window_manager,
            "pav_library",
            state,
            "library_index",
            rows=8,
        )
        if context.window_manager.pav_library:
            idx = min(max(state.library_index, 0), len(context.window_manager.pav_library) - 1)
            item = context.window_manager.pav_library[idx]
            from . import thumbs
            from .operators import _preview_path

            icon_value = thumbs.icon_id(item.product_id, _preview_path(context, item.product_id))
            box = layout.box()
            if icon_value:
                box.template_icon(icon_value=icon_value, scale=6.0)
            box.label(text=item.title)
            if item.author:
                box.label(text=item.author)
            row = layout.row(align=True)
            drag = row.operator("pav.drag_import", text="Drag into scene", icon="IMPORT")
            drag.product_id = item.product_id
            drag.title = item.title
            op_buy = row.operator("pav.buy", text="Open on site", icon="URL")
            op_buy.source = "LIBRARY"

    def _draw_list(self, layout, context, signed_in):
        if not signed_in:
            layout.label(text="Sign in on the Account tab first.")
            return
        state = context.window_manager.pav
        thumb = layout.box()
        thumb.label(text="Thumbnail")
        from . import thumbs
        from .api import is_png_file

        icon_value = thumbs.icon_id("listing_thumb", state.listing_thumb_file, rev=state.listing_thumb_rev)
        if icon_value:
            thumb.template_icon(icon_value=icon_value, scale=6.0)
        elif is_png_file(state.listing_thumb_file):
            thumb.label(text="PNG ready", icon="IMAGE_DATA")
        else:
            thumb.label(text="No PNG yet — capture or pick one.")
        thumb.prop(state, "listing_thumb_source", text="")
        thumb.label(text="Capture again after switching Viewport / Camera.")
        row = thumb.row(align=True)
        row.operator("pav.capture_thumbnail", icon="RENDER_STILL")
        row.operator("pav.pick_thumbnail", icon="FILEBROWSER")

        details = layout.box()
        details.label(text="Listing")
        col = details.column(align=True)
        col.prop(state, "listing_title")
        col.prop(state, "listing_short")
        col.prop(state, "listing_description")
        col.prop(state, "listing_tags")
        row = details.row(align=True)
        row.menu("PAV_MT_tags", text="Existing tags", icon="BOOKMARKS")
        from .api import suggest_tags

        known = [item.name for item in context.window_manager.pav_tags]
        suggestions = suggest_tags(state.listing_tags, known, limit=6)
        if suggestions:
            sug = details.row(align=True)
            for tag in suggestions:
                op = sug.operator("pav.use_tag", text=tag)
                op.tag = tag
        row = details.row(align=True)
        row.prop(state, "listing_price")
        row.prop(state, "listing_currency", text="")
        col = details.column(align=True)
        col.prop(state, "listing_category")
        col.prop(state, "listing_license")
        col.prop(state, "listing_status")
        col.prop(state, "listing_video")

        meta = layout.box()
        meta.label(text="From the scene")
        if state.listing_hint:
            meta.label(text=state.listing_hint, icon="INFO")
        meta.operator("pav.fill_listing", icon="FILE_REFRESH")
        col = meta.column(align=True)
        col.prop(state, "listing_polygon")
        row = meta.row(align=True)
        row.prop(state, "listing_rigged")
        row.prop(state, "listing_animated")
        row = meta.row(align=True)
        row.prop(state, "listing_uv")
        row.prop(state, "listing_render_ready")
        row.prop(state, "listing_lods")
        col = meta.column(align=True)
        col.prop(state, "listing_texture")
        col.prop(state, "listing_pbr")
        col.prop(state, "listing_engine")
        col.prop(state, "listing_scope")
        layout.operator("pav.list_asset", icon="EXPORT")
        layout.separator()
        layout.operator("pav.refresh_mine", icon="FILE_REFRESH")
        layout.template_list(
            "PAV_UL_products",
            "mine",
            context.window_manager,
            "pav_mine",
            state,
            "mine_index",
            rows=5,
        )
        if context.window_manager.pav_mine:
            layout.operator("pav.open_listing", icon="URL")


class FILEBROWSER_PT_pav(Panel):
    bl_label = "PolyAssetVault"
    bl_idname = "FILEBROWSER_PT_pav"
    bl_space_type = "FILE_BROWSER"
    bl_region_type = "TOOLS"
    bl_category = "PolyAssetVault"

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return bool(space and getattr(space, "browse_mode", None) == "ASSETS")

    def draw(self, context):
        layout = self.layout
        prefs = get_prefs(context)
        if not prefs.get_token():
            layout.label(text="Sign in from the 3D View N-panel first.")
            return
        layout.label(text="Library: PolyAssetVault")
        layout.operator("pav.sync_asset_browser", icon="FILE_REFRESH")
        layout.operator("pav.show_asset_shelf", icon="DOWNARROW_HLT")
        layout.label(text="Drag thumbnails into the 3D View.")


CLASSES = (PAV_PT_main, FILEBROWSER_PT_pav)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
