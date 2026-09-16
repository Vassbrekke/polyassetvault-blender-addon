"""Operators: sign in, browse, buy (browser checkout), import, list."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import webbrowser
import zipfile

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy.types import FileHandler, Operator, OperatorFileListElement, PropertyGroup, UIList

from .api import (
    ADDON_VERSION,
    CATEGORIES,
    AddonAPIError,
    AddonClient,
    category_api_slug,
    category_enum_id,
    category_enum_items,
    find_cached_asset,
    login_page_url,
    product_cache_dir,
    product_page_url,
)
from .auth import LoginCallback
from .prefs import get_prefs

_CATEGORY_ITEMS = category_enum_items()
_CATEGORY_FILTER = (("ALL", "All categories", ""),) + _CATEGORY_ITEMS


def _client(context) -> AddonClient:
    prefs = get_prefs(context)
    return AddonClient(prefs.api_base_url, token=prefs.get_token())


def _report_api(operator, exc: AddonAPIError):
    if exc.status == 401:
        try:
            get_prefs(bpy.context).clear_token()
        except Exception:
            pass
        operator.report({"ERROR"}, "Session expired. Sign in again.")
        return
    operator.report({"ERROR"}, str(exc))


def _fill_products(collection, products, *, owned_default=False):
    collection.clear()
    for product in products or []:
        item = collection.add()
        item.product_id = str(product.get("productId") or "")
        item.title = product.get("title") or "Untitled"
        item.author = product.get("author") or ""
        item.short_description = product.get("shortDescription") or ""
        item.category = product.get("category") or ""
        item.currency = product.get("currency") or "USD"
        try:
            item.price = float(product.get("price") or 0)
        except (TypeError, ValueError):
            item.price = 0.0
        item.owned = bool(product.get("owned", owned_default))
        item.status = product.get("status") or ""
        item.thumbnail = product.get("thumbnail") or ""


def _active_product(collection, index):
    if 0 <= index < len(collection):
        return collection[index]
    return None


def _resolve_download_dir(context) -> str:
    from .assets import library_root

    return library_root(context)


def _import_blend(filepath: str) -> list:
    imported_objects = []
    with bpy.data.libraries.load(filepath, link=False) as (data_from, data_to):
        data_to.objects = list(data_from.objects)
        data_to.collections = list(data_from.collections)
    scene_col = bpy.context.collection
    linked_collection = False
    if data_to.collections:
        for coll in data_to.collections:
            if coll is None:
                continue
            try:
                scene_col.children.link(coll)
                linked_collection = True
            except RuntimeError:
                pass
            imported_objects.extend([obj for obj in coll.objects if obj is not None])
    if not linked_collection:
        for obj in data_to.objects:
            if obj is None:
                continue
            try:
                scene_col.objects.link(obj)
                imported_objects.append(obj)
            except RuntimeError:
                pass
    return imported_objects


def _import_downloaded_objects(filepath: str) -> tuple[str, list]:
    lower = filepath.lower()
    if lower.endswith(".blend"):
        objects = _import_blend(filepath)
        return f"Imported {len(objects)} object(s) from {os.path.basename(filepath)}", objects
    if lower.endswith(".zip"):
        extract_dir = filepath + "_extracted"
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(filepath) as archive:
            archive.extractall(extract_dir)
        blends = []
        for root, _dirs, files in os.walk(extract_dir):
            for name in files:
                if name.lower().endswith(".blend"):
                    blends.append(os.path.join(root, name))
        if not blends:
            return (
                f"Downloaded {os.path.basename(filepath)} (no .blend inside). Extracted to {extract_dir}",
                [],
            )
        objects = []
        for blend in blends:
            objects.extend(_import_blend(blend))
        return f"Imported {len(objects)} object(s) from {len(blends)} .blend file(s)", objects
    return f"Saved {os.path.basename(filepath)} — open it from the download folder", []


def _place_objects(objects, location) -> None:
    if not objects or location is None:
        return
    try:
        from mathutils import Vector
    except ImportError:
        return
    imported = set(objects)
    coords = [obj.matrix_world.translation.copy() for obj in objects]
    if not coords:
        return
    center = sum(coords, Vector()) / len(coords)
    delta = Vector(location) - center
    for obj in objects:
        if obj.parent in imported:
            continue
        obj.location = obj.location + delta
    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)
    for obj in objects:
        try:
            obj.select_set(True)
        except RuntimeError:
            pass
    bpy.context.view_layer.objects.active = objects[0]


def _region_under_mouse(context, event):
    mx, my = event.mouse_x, event.mouse_y
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if not (area.x <= mx < area.x + area.width and area.y <= my < area.y + area.height):
                continue
            for region in area.regions:
                if region.x <= mx < region.x + region.width and region.y <= my < region.y + region.height:
                    return window, area, region
    return None, None, None


def _drop_location(context, event):
    from bpy_extras import view3d_utils

    fallback = context.scene.cursor.location.copy()
    _window, area, region = _region_under_mouse(context, event)
    if area is None or area.type != "VIEW_3D" or region is None or region.type != "WINDOW":
        return fallback
    space = area.spaces.active
    rv3d = getattr(space, "region_3d", None)
    if rv3d is None:
        return fallback
    coord = (event.mouse_x - region.x, event.mouse_y - region.y)
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
    direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
    depsgraph = context.evaluated_depsgraph_get()
    hit, loc, _normal, _index, _obj, _matrix = context.scene.ray_cast(depsgraph, origin, direction)
    if hit:
        return loc
    return view3d_utils.region_2d_to_location_3d(region, rv3d, coord, fallback)


def _ensure_local_file(context, product_id: str) -> str:
    dest_dir = product_cache_dir(_resolve_download_dir(context), product_id)
    cached = find_cached_asset(dest_dir)
    if cached:
        return cached
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, "download.bin")
    return _client(context).download_product(product_id, dest)


def _import_product_at(context, product_id: str, location) -> str:
    saved = _ensure_local_file(context, product_id)
    message, objects = _import_downloaded_objects(saved)
    _place_objects(objects, location)
    return message


def _redraw_view3d(context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


# ── Property groups ──────────────────────────────────────────────────────────


class PAV_PG_product(PropertyGroup):
    product_id: StringProperty()
    title: StringProperty()
    author: StringProperty()
    short_description: StringProperty()
    category: StringProperty()
    currency: StringProperty()
    price: FloatProperty()
    owned: BoolProperty()
    status: StringProperty()
    thumbnail: StringProperty()


class PAV_PG_state(PropertyGroup):
    tab: EnumProperty(
        name="Tab",
        items=(
            ("ACCOUNT", "Account", "Sign in and account status"),
            ("BROWSE", "Browse", "Search the marketplace"),
            ("LIBRARY", "Library", "Purchased assets"),
            ("LIST", "List", "Publish a listing from this file"),
        ),
        default="ACCOUNT",
    )
    search: StringProperty(name="Search", default="")
    category: EnumProperty(name="Category", items=_CATEGORY_FILTER, default="ALL")
    browse_index: IntProperty(name="Browse index", default=0)
    library_index: IntProperty(name="Library index", default=0)
    mine_index: IntProperty(name="My listings index", default=0)
    listing_title: StringProperty(name="Title", default="")
    listing_description: StringProperty(name="Description", default="", subtype="NONE")
    listing_tags: StringProperty(name="Tags", description="Comma-separated", default="blender")
    listing_price: FloatProperty(name="Price", default=0.0, min=0.0, soft_max=999)
    listing_category: EnumProperty(name="Category", items=_CATEGORY_ITEMS, default="cat_3d_models")
    listing_status: EnumProperty(
        name="Status",
        items=(
            ("draft", "Draft", "Save without publishing"),
            ("published", "Published", "List on the marketplace"),
        ),
        default="draft",
    )
    listing_scope: EnumProperty(
        name="Contents",
        items=(
            ("SELECTED", "Selected objects", "Write a new .blend from the selection"),
            ("FILE", "Entire file", "Upload a copy of this .blend"),
        ),
        default="SELECTED",
    )
    status_message: StringProperty(name="Status", default="")
    account_name: StringProperty(default="")
    account_type: StringProperty(default="")
    stripe_connected: BoolProperty(default=False)


class PAV_UL_products(UIList):
    bl_idname = "PAV_UL_products"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        if item.owned:
            op = row.operator("pav.drag_import", text=item.title or "Untitled", icon="MESH_CUBE", emboss=False)
            op.product_id = item.product_id
            op.title = item.title
        else:
            row.label(text=item.title or "Untitled", icon="MESH_CUBE")
            if item.status:
                row.label(text=item.status)
            else:
                price = "Free" if item.price <= 0 else f"{item.currency} {item.price:g}"
                row.label(text=price)
            if item.author:
                row.label(text=item.author)


# ── Auth ─────────────────────────────────────────────────────────────────────


class PAV_OT_login(Operator):
    bl_idname = "pav.login"
    bl_label = "Sign in"
    bl_description = "Open the PolyAssetVault sign-in page and link this Blender"

    _callback: LoginCallback | None = None
    _timer = None

    def invoke(self, context, event):
        prefs = get_prefs(context)
        if not prefs.site_url or not prefs.api_base_url:
            self.report({"ERROR"}, "Set Site URL and API base URL in addon preferences.")
            return {"CANCELLED"}
        callback = LoginCallback()
        try:
            port = callback.start()
        except Exception as exc:
            self.report({"ERROR"}, f"Could not start login listener: {exc}")
            return {"CANCELLED"}
        url = login_page_url(prefs.site_url, port, callback.state)
        webbrowser.open(url)
        self._callback = callback
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.4, window=context.window)
        wm.modal_handler_add(self)
        state = context.window_manager.pav
        state.status_message = "Waiting for browser sign-in…"
        self.report({"INFO"}, "Complete sign-in in the browser, then return here.")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        callback = self._callback
        if event.type == "ESC":
            self._cleanup(context)
            self.report({"INFO"}, "Sign-in cancelled.")
            return {"CANCELLED"}
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        if callback is None:
            self._cleanup(context)
            return {"CANCELLED"}
        if callback.error:
            self.report({"ERROR"}, callback.error)
            self._cleanup(context)
            return {"CANCELLED"}
        jwt = callback.poll()
        if jwt:
            return self._exchange(context, jwt)
        if callback.expired():
            self.report({"ERROR"}, "Sign-in timed out.")
            self._cleanup(context)
            return {"CANCELLED"}
        return {"PASS_THROUGH"}

    def _exchange(self, context, jwt: str):
        prefs = get_prefs(context)
        client = AddonClient(prefs.api_base_url)
        try:
            payload = client.issue_device_token(
                jwt,
                device_name=f"Blender {bpy.app.version_string}",
                blender_version=getattr(bpy.app, "version_string", ""),
                addon_version=ADDON_VERSION,
                platform=sys.platform,
            )
        except AddonAPIError as exc:
            _report_api(self, exc)
            self._cleanup(context)
            return {"CANCELLED"}
        token = payload.get("deviceToken") or ""
        if not token:
            self.report({"ERROR"}, "Server did not return a device token.")
            self._cleanup(context)
            return {"CANCELLED"}
        prefs.set_token(token)
        self._cleanup(context)
        bpy.ops.pav.refresh_account()
        self.report({"INFO"}, f"Signed in as {payload.get('username') or 'user'}.")
        return {"FINISHED"}

    def _cleanup(self, context):
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        if self._callback is not None:
            self._callback.stop()
            self._callback = None


class PAV_OT_logout(Operator):
    bl_idname = "pav.logout"
    bl_label = "Sign out"

    def execute(self, context):
        prefs = get_prefs(context)
        if prefs.get_token():
            try:
                _client(context).logout()
            except AddonAPIError:
                pass
        prefs.clear_token()
        wm = context.window_manager
        wm.pav_browse.clear()
        wm.pav_library.clear()
        wm.pav_mine.clear()
        wm.pav.account_name = ""
        wm.pav.status_message = "Signed out"
        self.report({"INFO"}, "Signed out.")
        return {"FINISHED"}


class PAV_OT_refresh_account(Operator):
    bl_idname = "pav.refresh_account"
    bl_label = "Refresh account"

    def execute(self, context):
        try:
            me = _client(context).me()
        except AddonAPIError as exc:
            _report_api(self, exc)
            return {"CANCELLED"}
        state = context.window_manager.pav
        state.account_name = me.get("displayName") or me.get("username") or ""
        state.account_type = me.get("userType") or ""
        state.stripe_connected = bool(me.get("stripeConnected"))
        state.status_message = f"Signed in as {state.account_name}"
        return {"FINISHED"}


# ── Browse / library ─────────────────────────────────────────────────────────


class PAV_OT_browse(Operator):
    bl_idname = "pav.browse"
    bl_label = "Search marketplace"

    def execute(self, context):
        state = context.window_manager.pav
        try:
            data = _client(context).browse(
                search=state.search,
                category=category_api_slug(state.category),
                page=1,
                limit=30,
            )
        except AddonAPIError as exc:
            _report_api(self, exc)
            return {"CANCELLED"}
        _fill_products(context.window_manager.pav_browse, data.get("products") or [])
        state.browse_index = 0
        state.status_message = f"{data.get('total', len(context.window_manager.pav_browse))} listing(s)"
        return {"FINISHED"}


class PAV_OT_refresh_library(Operator):
    bl_idname = "pav.refresh_library"
    bl_label = "Refresh library"

    def execute(self, context):
        try:
            data = _client(context).purchases()
        except AddonAPIError as exc:
            _report_api(self, exc)
            return {"CANCELLED"}
        _fill_products(
            context.window_manager.pav_library,
            data.get("purchases") or [],
            owned_default=True,
        )
        context.window_manager.pav.status_message = (
            f"{data.get('total', len(context.window_manager.pav_library))} purchase(s)"
        )
        return {"FINISHED"}


class PAV_OT_refresh_mine(Operator):
    bl_idname = "pav.refresh_mine"
    bl_label = "Refresh my listings"

    def execute(self, context):
        try:
            data = _client(context).my_products()
        except AddonAPIError as exc:
            _report_api(self, exc)
            return {"CANCELLED"}
        _fill_products(context.window_manager.pav_mine, data.get("products") or [])
        context.window_manager.pav.status_message = (
            f"{data.get('total', len(context.window_manager.pav_mine))} of your listing(s)"
        )
        return {"FINISHED"}


class PAV_OT_buy(Operator):
    bl_idname = "pav.buy"
    bl_label = "Buy on PolyAssetVault"
    bl_description = "Open checkout in the browser. Cards never go through Blender."

    source: EnumProperty(
        items=(("BROWSE", "Browse", ""), ("LIBRARY", "Library", "")),
        default="BROWSE",
    )

    def execute(self, context):
        wm = context.window_manager
        item = (
            _active_product(wm.pav_browse, wm.pav.browse_index)
            if self.source == "BROWSE"
            else _active_product(wm.pav_library, wm.pav.library_index)
        )
        if item is None or not item.product_id:
            self.report({"ERROR"}, "Select a product first.")
            return {"CANCELLED"}
        url = product_page_url(get_prefs(context).site_url, item.product_id)
        webbrowser.open(url)
        wm.pav.status_message = "Checkout opened in the browser. Refresh Library after paying."
        self.report({"INFO"}, "Finish payment in the browser, then refresh Library.")
        return {"FINISHED"}


class PAV_OT_open_listing(Operator):
    bl_idname = "pav.open_listing"
    bl_label = "Open listing on site"

    def execute(self, context):
        wm = context.window_manager
        item = _active_product(wm.pav_mine, wm.pav.mine_index)
        if item is None or not item.product_id:
            self.report({"ERROR"}, "Select a listing first.")
            return {"CANCELLED"}
        webbrowser.open(product_page_url(get_prefs(context).site_url, item.product_id))
        return {"FINISHED"}


class PAV_OT_import_product(Operator):
    bl_idname = "pav.import_product"
    bl_label = "Import into scene"
    bl_description = "Download a purchased asset and append it at the 3D cursor"
    bl_options = {"REGISTER", "UNDO"}

    source: EnumProperty(
        items=(("BROWSE", "Browse", ""), ("LIBRARY", "Library", "")),
        default="LIBRARY",
    )

    def execute(self, context):
        wm = context.window_manager
        item = (
            _active_product(wm.pav_library, wm.pav.library_index)
            if self.source == "LIBRARY"
            else _active_product(wm.pav_browse, wm.pav.browse_index)
        )
        if item is None or not item.product_id:
            self.report({"ERROR"}, "Select a purchased product first.")
            return {"CANCELLED"}
        try:
            message = _import_product_at(context, item.product_id, context.scene.cursor.location.copy())
        except AddonAPIError as exc:
            _report_api(self, exc)
            return {"CANCELLED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Import failed: {exc}")
            return {"CANCELLED"}
        wm.pav.status_message = message
        self.report({"INFO"}, message)
        return {"FINISHED"}


class PAV_OT_drag_import(Operator):
    bl_idname = "pav.drag_import"
    bl_label = "Drag into scene"
    bl_description = "Press and drag a purchased asset into the 3D view, then release to drop it"
    bl_options = {"REGISTER", "UNDO"}

    product_id: StringProperty()
    title: StringProperty()

    _handle = None

    def _draw_hud(self, context):
        try:
            import blf
        except ImportError:
            return
        label = self.title or "asset"
        font_id = 0
        blf.size(font_id, 18)
        blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
        blf.position(font_id, 24, 48, 0)
        blf.draw(font_id, f"Drop “{label}” into the scene")
        blf.size(font_id, 12)
        blf.position(font_id, 24, 30, 0)
        blf.draw(font_id, "Release over the viewport  ·  Esc to cancel")

    def invoke(self, context, event):
        if not self.product_id:
            item = _active_product(context.window_manager.pav_library, context.window_manager.pav.library_index)
            if item is None or not item.product_id:
                item = _active_product(context.window_manager.pav_browse, context.window_manager.pav.browse_index)
            if item is None or not item.product_id:
                self.report({"ERROR"}, "Select a purchased product first.")
                return {"CANCELLED"}
            self.product_id = item.product_id
            self.title = item.title
        context.window.cursor_modal_set("SCROLL_XY")
        try:
            context.workspace.status_text_set(f"Drop “{self.title or 'asset'}” into the 3D view")
        except Exception:
            pass
        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_hud, (context,), "WINDOW", "POST_PIXEL"
        )
        context.window_manager.modal_handler_add(self)
        _redraw_view3d(context)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"RIGHTMOUSE", "ESC"}:
            self._cleanup(context)
            self.report({"INFO"}, "Drop cancelled.")
            return {"CANCELLED"}
        if event.type == "MOUSEMOVE":
            _redraw_view3d(context)
            return {"RUNNING_MODAL"}
        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            location = _drop_location(context, event)
            try:
                message = _import_product_at(context, self.product_id, location)
            except AddonAPIError as exc:
                self._cleanup(context)
                _report_api(self, exc)
                return {"CANCELLED"}
            except Exception as exc:
                self._cleanup(context)
                self.report({"ERROR"}, f"Import failed: {exc}")
                return {"CANCELLED"}
            context.window_manager.pav.status_message = message
            self._cleanup(context)
            self.report({"INFO"}, message)
            return {"FINISHED"}
        return {"RUNNING_MODAL"}

    def execute(self, context):
        if not self.product_id:
            item = _active_product(context.window_manager.pav_library, context.window_manager.pav.library_index)
            if item is None or not item.product_id:
                self.report({"ERROR"}, "Select a purchased product first.")
                return {"CANCELLED"}
            self.product_id = item.product_id
        try:
            message = _import_product_at(context, self.product_id, context.scene.cursor.location.copy())
        except AddonAPIError as exc:
            _report_api(self, exc)
            return {"CANCELLED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Import failed: {exc}")
            return {"CANCELLED"}
        context.window_manager.pav.status_message = message
        self.report({"INFO"}, message)
        return {"FINISHED"}

    def _cleanup(self, context):
        try:
            context.window.cursor_modal_restore()
        except Exception:
            pass
        try:
            context.workspace.status_text_set(None)
        except Exception:
            pass
        if self._handle is not None:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(self._handle, "WINDOW")
            except Exception:
                pass
            self._handle = None
        _redraw_view3d(context)


class PAV_OT_drop_files(Operator):
    bl_idname = "pav.drop_files"
    bl_label = "Drop asset files into scene"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    directory: StringProperty(subtype="DIR_PATH", options={"SKIP_SAVE", "HIDDEN"})
    files: CollectionProperty(type=OperatorFileListElement, options={"SKIP_SAVE", "HIDDEN"})

    def invoke(self, context, event):
        location = _drop_location(context, event)
        return self._import_listed(context, location)

    def execute(self, context):
        return self._import_listed(context, context.scene.cursor.location.copy())

    def _import_listed(self, context, location):
        imported = []
        names = []
        for entry in self.files:
            path = os.path.join(self.directory, entry.name)
            if not os.path.isfile(path):
                continue
            _message, objects = _import_downloaded_objects(path)
            imported.extend(objects)
            names.append(entry.name)
        if not names:
            self.report({"ERROR"}, "No .blend or .zip to import.")
            return {"CANCELLED"}
        _place_objects(imported, location)
        message = f"Dropped {len(names)} file(s), {len(imported)} object(s)"
        context.window_manager.pav.status_message = message
        self.report({"INFO"}, message)
        return {"FINISHED"}


class PAV_FH_blend(FileHandler):
    bl_idname = "PAV_FH_blend"
    bl_label = "Import PolyAssetVault asset"
    bl_import_operator = "pav.drop_files"
    bl_file_extensions = ".blend;.zip"

    @classmethod
    def poll_drop(cls, context):
        area = getattr(context, "area", None)
        region = getattr(context, "region", None)
        return bool(area and area.type == "VIEW_3D" and region and region.type == "WINDOW")


# ── List / sell ──────────────────────────────────────────────────────────────


class PAV_OT_list_asset(Operator):
    bl_idname = "pav.list_asset"
    bl_label = "Upload listing"
    bl_description = "Export the selection or this file and create a marketplace listing"

    def invoke(self, context, event):
        return self._begin(context, modal=True)

    def execute(self, context):
        return self._begin(context, modal=False)

    def _validate(self, context):
        state = context.window_manager.pav
        title = (state.listing_title or "").strip()
        if not title:
            return "Give the listing a title."
        price = float(state.listing_price or 0)
        if price > 0 and price < 1:
            return "Price must be free (0) or at least 1.00."
        if state.listing_scope == "SELECTED" and not context.selected_objects:
            return "Select objects to list, or switch to Entire file."
        return ""

    def _begin(self, context, modal: bool):
        err = self._validate(context)
        if err:
            self.report({"ERROR"}, err)
            return {"CANCELLED"}
        state = context.window_manager.pav
        state.status_message = "Exporting listing…"
        tmp = tempfile.mkdtemp(prefix="pav_list_")
        blend_path = os.path.join(tmp, "download.blend")
        thumb_path = os.path.join(tmp, "preview.png")
        try:
            if state.listing_scope == "SELECTED":
                datablocks = set(context.selected_objects)
                bpy.data.libraries.write(blend_path, datablocks, fake_user=True)
            else:
                bpy.ops.wm.save_as_mainfile(filepath=blend_path, copy=True, check_existing=False)
            self._write_thumbnail(context, thumb_path)
        except Exception as exc:
            self.report({"ERROR"}, f"Could not export: {exc}")
            return {"CANCELLED"}

        files = [blend_path]
        if os.path.isfile(thumb_path):
            files.append(thumb_path)
        title = (state.listing_title or "").strip()
        fields = {
            "title": title,
            "description": state.listing_description or title,
            "shortDescription": (state.listing_description or title)[:240],
            "price": f"{float(state.listing_price or 0):g}",
            "currency": "USD",
            "category": category_api_slug(state.listing_category) or "3d-models",
            "tags": state.listing_tags or "blender",
            "status": state.listing_status,
            "fileFormat": "BLEND",
            "softwareVersion": getattr(bpy.app, "version_string", ""),
            "compatibility": '{"blender": true}',
            "license": "CC BY 4.0",
        }
        client = _client(context)
        if not modal:
            return self._finish_upload(context, client, fields, files, title, state.listing_status)

        state.status_message = "Uploading listing… (Blender stays interactive)"
        self._upload = {"result": None, "error": None, "title": title, "status": state.listing_status}
        thread = threading.Thread(
            target=self._upload_worker,
            args=(client, fields, files),
            daemon=True,
        )
        self._thread = thread
        thread.start()
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.2, window=context.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def _upload_worker(self, client, fields, files):
        try:
            self._upload["result"] = client.create_product(fields, files)
        except Exception as exc:
            self._upload["error"] = exc

    def modal(self, context, event):
        if event.type == "ESC":
            context.window_manager.pav.status_message = "Upload still running in the background…"
            self._cleanup_timer(context)
            return {"CANCELLED"}
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        if self._thread.is_alive():
            return {"PASS_THROUGH"}
        self._cleanup_timer(context)
        error = self._upload.get("error")
        if error:
            if isinstance(error, AddonAPIError):
                _report_api(self, error)
            else:
                self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return self._apply_created(
            context,
            self._upload.get("result") or {},
            self._upload.get("title") or "",
            self._upload.get("status") or "draft",
        )

    def _finish_upload(self, context, client, fields, files, title, status):
        try:
            created = client.create_product(fields, files)
        except AddonAPIError as exc:
            _report_api(self, exc)
            return {"CANCELLED"}
        return self._apply_created(context, created, title, status)

    def _apply_created(self, context, created, title, status):
        if isinstance(created, dict) and created.get("errors"):
            self.report({"WARNING"}, f"Listed with warnings: {created.get('errors')}")
        product_id = str(
            (created or {}).get("_id")
            or (created or {}).get("productId")
            or ((created or {}).get("product") or {}).get("_id")
            or ""
        )
        state = context.window_manager.pav
        state.status_message = f"Listed '{title}' as {status}" + (f" ({product_id})" if product_id else "")
        try:
            bpy.ops.pav.refresh_mine()
        except Exception:
            pass
        self.report({"INFO"}, state.status_message)
        return {"FINISHED"}

    def _cleanup_timer(self, context):
        if getattr(self, "_timer", None) is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None

    def _write_thumbnail(self, context, path: str) -> None:
        scene = context.scene
        render = scene.render
        old_path = render.filepath
        old_format = render.image_settings.file_format
        old_x = render.resolution_x
        old_y = render.resolution_y
        old_pct = render.resolution_percentage
        try:
            render.filepath = path
            render.image_settings.file_format = "PNG"
            render.resolution_x = min(old_x, 768)
            render.resolution_y = min(old_y, 768)
            render.resolution_percentage = min(old_pct, 50)
            bpy.ops.render.opengl(write_still=True)
        finally:
            render.filepath = old_path
            render.image_settings.file_format = old_format
            render.resolution_x = old_x
            render.resolution_y = old_y
            render.resolution_percentage = old_pct


class PAV_OT_open_prefs(Operator):
    bl_idname = "pav.open_prefs"
    bl_label = "Addon preferences"

    def execute(self, context):
        bpy.ops.screen.userpref_show("INVOKE_DEFAULT")
        return {"FINISHED"}


class PAV_OT_show_asset_shelf(Operator):
    bl_idname = "pav.show_asset_shelf"
    bl_label = "Show Asset Shelf"
    bl_description = "Open the Asset Shelf at the bottom of the 3D View"

    def execute(self, context):
        from .assets import ensure_user_library, show_asset_shelf

        ensure_user_library(context)
        shown = show_asset_shelf(context)
        if not shown:
            self.report({"WARNING"}, "No 3D View to show the Asset Shelf on.")
            return {"CANCELLED"}
        self.report({"INFO"}, "Asset Shelf is open. Pick library PolyAssetVault if it is not selected.")
        return {"FINISHED"}


class PAV_OT_open_asset_browser(Operator):
    bl_idname = "pav.open_asset_browser"
    bl_label = "Open Asset Browser"
    bl_description = "Turn a spare editor into the Asset Browser (library PolyAssetVault)"

    def execute(self, context):
        from .assets import ensure_user_library, open_asset_browser_area, refresh_asset_ui

        ensure_user_library(context)
        refresh_asset_ui(context)
        if not open_asset_browser_area(context):
            self.report(
                {"WARNING"},
                "Split an editor, set Editor Type to Asset Browser, then choose library PolyAssetVault.",
            )
            return {"CANCELLED"}
        self.report({"INFO"}, "Asset Browser opened. Choose library PolyAssetVault in its header.")
        return {"FINISHED"}


class PAV_OT_sync_asset_browser(Operator):
    bl_idname = "pav.sync_asset_browser"
    bl_label = "Sync to Asset Browser"
    bl_description = "Download purchases and index them so they appear in the Asset Shelf and Asset Browser"

    def invoke(self, context, event):
        return self._start(context)

    def execute(self, context):
        return self._start(context)

    def _start(self, context):
        from .assets import ensure_user_library, library_root
        from .api import find_cached_asset, product_cache_dir

        try:
            ensure_user_library(context)
        except Exception as exc:
            self.report({"ERROR"}, f"Could not register asset library: {exc}")
            return {"CANCELLED"}
        wm = context.window_manager
        items = list(wm.pav_library)
        if not items:
            try:
                data = _client(context).purchases()
            except AddonAPIError as exc:
                _report_api(self, exc)
                return {"CANCELLED"}
            _fill_products(wm.pav_library, data.get("purchases") or [], owned_default=True)
            items = list(wm.pav_library)
        if not items:
            self.report({"WARNING"}, "No purchases to sync.")
            return {"CANCELLED"}
        jobs = [
            {"product_id": item.product_id, "title": item.title, "author": item.author}
            for item in items
            if item.product_id
        ]
        from .assets import run_mark_blend

        blender_bin = getattr(bpy.app, "binary_path", "") or ""
        script = os.path.join(os.path.dirname(__file__), "mark_assets.py")
        root = library_root(context)
        client = _client(context)
        self._sync = {
            "progress": "Starting…",
            "done": False,
            "indexed": 0,
            "failed": 0,
            "error": None,
        }

        def worker():
            indexed = 0
            failed = 0
            try:
                for i, job in enumerate(jobs, start=1):
                    self._sync["progress"] = f"Syncing {i}/{len(jobs)}: {job['title'] or job['product_id']}"
                    try:
                        dest_dir = product_cache_dir(root, job["product_id"])
                        saved = find_cached_asset(dest_dir)
                        if not saved:
                            os.makedirs(dest_dir, exist_ok=True)
                            saved = client.download_product(
                                job["product_id"], os.path.join(dest_dir, "download.bin")
                            )
                        if saved and saved.lower().endswith(".blend"):
                            if run_mark_blend(
                                blender_bin,
                                script,
                                saved,
                                title=job["title"],
                                author=job["author"],
                            ):
                                indexed += 1
                            else:
                                failed += 1
                        elif saved and saved.lower().endswith(".zip"):
                            indexed += 1
                    except Exception:
                        failed += 1
                    self._sync["indexed"] = indexed
                    self._sync["failed"] = failed
            except Exception as exc:
                self._sync["error"] = str(exc)
            self._sync["done"] = True

        self._thread = threading.Thread(target=worker, daemon=True)
        self._thread.start()
        wm.pav.status_message = f"Syncing {len(jobs)} purchase(s)…"
        wm.progress_begin(0, max(len(jobs), 1))
        self._timer = wm.event_timer_add(0.25, window=context.window)
        wm.modal_handler_add(self)
        self.report({"INFO"}, "Sync running in the background. Keep Blender open.")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "ESC":
            return {"RUNNING_MODAL"}
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        state = self._sync
        context.window_manager.pav.status_message = state.get("progress") or "Syncing…"
        try:
            context.window_manager.progress_update(int(state.get("indexed") or 0))
        except Exception:
            pass
        if not state.get("done"):
            return {"PASS_THROUGH"}
        self._stop_progress(context)
        from .assets import refresh_asset_ui, show_asset_shelf

        refresh_asset_ui(context)
        show_asset_shelf(context)
        message = f"Indexed {state.get('indexed', 0)} asset file(s)"
        if state.get("failed"):
            message += f", {state.get('failed')} failed"
        if state.get("error"):
            message += f" ({state['error']})"
        context.window_manager.pav.status_message = message
        self.report({"INFO"}, message + ". Drag from the Asset Shelf or Asset Browser.")
        return {"FINISHED"}

    def _stop_progress(self, context):
        try:
            context.window_manager.progress_end()
        except Exception:
            pass
        if getattr(self, "_timer", None) is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None


CLASSES = (
    PAV_PG_product,
    PAV_PG_state,
    PAV_UL_products,
    PAV_OT_login,
    PAV_OT_logout,
    PAV_OT_refresh_account,
    PAV_OT_browse,
    PAV_OT_refresh_library,
    PAV_OT_refresh_mine,
    PAV_OT_buy,
    PAV_OT_open_listing,
    PAV_OT_import_product,
    PAV_OT_drag_import,
    PAV_OT_drop_files,
    PAV_FH_blend,
    PAV_OT_list_asset,
    PAV_OT_open_prefs,
    PAV_OT_show_asset_shelf,
    PAV_OT_open_asset_browser,
    PAV_OT_sync_asset_browser,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.pav = bpy.props.PointerProperty(type=PAV_PG_state)
    bpy.types.WindowManager.pav_browse = bpy.props.CollectionProperty(type=PAV_PG_product)
    bpy.types.WindowManager.pav_library = bpy.props.CollectionProperty(type=PAV_PG_product)
    bpy.types.WindowManager.pav_mine = bpy.props.CollectionProperty(type=PAV_PG_product)


def unregister():
    del bpy.types.WindowManager.pav_mine
    del bpy.types.WindowManager.pav_library
    del bpy.types.WindowManager.pav_browse
    del bpy.types.WindowManager.pav
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
