# PolyAssetVault Blender addon

Connect Blender 4.2+ to the PolyAssetVault marketplace. Sign in through the existing browser flow, browse listings, buy via the website checkout, import purchased `.blend` files, and list assets from the current scene.

This folder is the **client**. Auth, catalog, downloads, and listing already live on the Market backend at `/api/addon/*`.

## Install

Blender 4.2 or newer.

1. Zip the `polyassetvault` directory (or run `./pack.sh` in this folder).
2. Blender → *Edit* → *Preferences* → *Get Extensions* → *Install from Disk…* (or *Add-ons* → *Install…* on older layouts).
3. Enable **PolyAssetVault**.
4. Open a 3D View, press `N`, open the **PolyAssetVault** tab.

Production defaults:

- Site URL: `https://polyassetvault.com`
- API base: `https://polyassetvault.com`

Local development (backend on 5000, Vite on 5173):

- Site URL: `http://localhost:5173`
- API base: `http://localhost:5000`

## What it does

| Tab | Action |
|-----|--------|
| Account | Browser sign-in at `/addon-login?port=&state=`. Exchanges the JWT for a 30-day `X-Addon-Token`. |
| Browse | `GET /api/addon/products`. **Buy** opens `/product/:id` in the browser — cards never enter Blender. |
| Library | Purchases. **Sync to Asset Browser**, then drag from the **Asset Shelf** (bottom of the 3D View) or the **Asset Browser**. Rows in the N-panel still drag too. |
| List | Export selected objects or the whole file as `download.blend` plus a viewport preview, `POST /api/addon/products` as `files`. |

There is no addon Stripe endpoint. Paid checkout stays on the website. After paying, **Sync to Asset Browser**, then drag from the shelf.

## Asset Shelf and Asset Browser

After sign-in, open **Library** and click **Sync to Asset Browser**. That downloads purchases, marks objects as Blender assets, and registers a user library named **PolyAssetVault**.

- **Show Asset Shelf** — thumbnail strip at the bottom of the 3D View. Drag into the scene.
- **Open Asset Browser** — turns the spare editor (e.g. the Scripting text area) into an Asset Browser. In its header pick library **PolyAssetVault**, then drag.

First sync can take a while (one background Blender pass per `.blend`). The UI stays interactive and the N-panel shows `Syncing 3/12…`. Listing uploads on a background thread after a short local export.


## Tests (no Blender)

```bash
cd blender-addon
python3 -m unittest discover -s tests -v
```

`api.py` and `auth.py` are stdlib-only so they can run on this host without `bpy`. This machine does not currently have a `blender` binary, so the N-panel is not smoke-tested here.

## Layout

```
blender-addon/
├── pack.sh
├── README.md
├── tests/
└── polyassetvault/          ← install this folder
    ├── blender_manifest.toml
    ├── __init__.py
    ├── api.py
    ├── auth.py
    ├── prefs.py
    ├── operators.py
    └── ui.py
```

GPL-2.0-or-later (Blender addon requirement).
