# PolyAssetVault for Blender

Official Blender addon for [polyassetvault.com](https://polyassetvault.com). Browse, buy, import, and list 3D assets without leaving Blender.

Checkout stays on the website. Card details never enter this addon.

This repository is the published source for the addon (Vassbrekke AS). Publishing the source lets you inspect it. That is not an independent third-party security audit.

**Requires Blender 4.2 or newer** (including 5.2 LTS). Needs a PolyAssetVault account and internet access.

---

## Install

1. Download the latest `polyassetvault-<version>.zip` from [Releases](https://github.com/Vassbrekke/polyassetvault-blender-addon/releases).
2. In Blender: **Edit → Preferences → Get Extensions → Install from Disk…**  
   (older layouts: **Add-ons → Install…**)
3. Enable **PolyAssetVault**.
4. Open a **3D Viewport**, press **N**, and open the **PolyAssetVault** tab.

The sidebar only appears over a 3D View. It will not show in the Scripting workspace, Text Editor, or Outliner.

Use the zip from Releases. Do not install a random folder copy from a clone unless you are developing.

### Update

Quit Blender. Install the newer zip over the old one. If enable fails, delete the previous install first, then install from disk again:

| OS | Folder to remove |
| --- | --- |
| Linux | `~/.config/blender/<version>/extensions/user_default/polyassetvault` |
| macOS | `~/Library/Application Support/Blender/<version>/extensions/user_default/polyassetvault` |
| Windows | `%APPDATA%\Blender Foundation\Blender\<version>\extensions\user_default\polyassetvault` |

Use your Blender version in that path (`4.2`, `5.2`, …). Confirm **Addon version** in Preferences matches the release.

---

## Where to find it

| Place | What it does |
| --- | --- |
| **3D View → N → PolyAssetVault** | Account, Browse, Library, List |
| **PAV** in the 3D View header | Shortcuts for sign-in, browse, library, list, shelf |
| **Add → PolyAssetVault** | Opens the Asset Shelf |
| **File → Import → PolyAssetVault Library** | Opens your purchased library |
| **Asset Shelf** (bottom of the 3D View) | Thumbnail strip — drag into the scene |
| **Asset Browser** | Full grid. In the header, pick library **PolyAssetVault** |

---

## Sign in

1. **Account** tab → **Sign in with browser**.
2. Log in on [polyassetvault.com](https://polyassetvault.com). The page sends a device token back to Blender.
3. You stay signed in for 30 days.

Set a **Download folder** on the Account tab if you want purchases somewhere specific, then **Save preferences now**. Blender on Windows often has Auto-Save Preferences off, so that button matters.

Do not share the device token. Treat it like a password for this Blender install.

Payouts for paid listings are connected on the website (Stripe), not in the addon.

---

## Browse and buy

1. **Browse** — search and filter the catalog.
2. **Buy** opens the product page in your browser. Pay there.
3. Come back to Blender, open **Library**, and refresh.

Nothing in the addon collects card details.

---

## Library — use what you bought

1. **Library → Sync to Asset Browser.**  
   Downloads purchases, marks them as Blender assets, and stamps marketplace thumbnails as previews.
2. **Show Asset Shelf** or **Open Asset Browser**, then drag into the scene.
3. Or drag a row from the Library list straight into the 3D View.

Choose **Append** (copy into this file) or **Link** (reference the library file) on the Library tab.

First sync can take a while (one background pass per `.blend`). Blender stays interactive; the panel shows `Syncing 3/12…`.

---

## List — publish from this file

Select the objects you want to list (or switch to **Entire file**).

1. Open the **List** tab — empty fields fill from the selection.
2. **Fill from scene** if you want a fresh read (title, tags, polys, size, UVs, PBR, rig, animation, engine, category).
3. Frame the asset. **Capture thumbnail** (3D Viewport or Camera render) or **Pick thumbnail**. You should see the PNG in the panel. Capture again after switching Viewport / Camera.
4. Set **price**, **license**, and **Draft / Published**. Draft is the safe default. Price is free (`0`) or at least `1.00`.
5. Paid listings require Stripe payouts connected on the website. Without Stripe, the addon only allows free listings.
6. Use **Existing tags** or the suggestion chips so spellings match the catalog.
7. **Upload listing**.

The PNG is sent first (that is the catalog thumbnail), then the `.blend`. Upload refuses to continue without a real PNG. After a successful list, **Open on site** to review.

You still choose price, license, and whether it goes live. Everything else is filled from the scene so you do not have to re-enter it on the website.

If your scene output is set to video (FFmpeg), thumbnail capture still writes a PNG and restores your output settings.

---

## Preferences

**Edit → Preferences → Add-ons → PolyAssetVault**, or **Account → All settings**.

| Setting | Production default |
| --- | --- |
| Site URL | `https://polyassetvault.com` |
| API base | `https://polyassetvault.com` |
| Download folder | Blender’s data files (`polyassetvault/library`) |

Leave Site URL and API base on the production defaults unless you were told to change them. Use **Save preferences now** after changing the download folder.

---

## Troubleshooting

**I don’t see the tab.**  
Mouse over a 3D Viewport and press **N**. Layout workspace is easier than Scripting. Confirm the add-on is enabled.

**Enable error after an update.**  
Quit Blender, remove the install folder in the table above, then install the latest zip from Releases.

**Library previews are missing.**  
Sync again. Thumbnails come from the marketplace listing.

**Sidebar thumbnail didn’t change after recapture.**  
Capture again. Switch to **Camera render** if the viewport capture looks too small.

**Listing has no picture on the site.**  
Capture or pick a PNG *before* upload. If the first file is the `.blend`, the site treats that as the thumbnail.

**Listing has no `.blend`.**  
Use **Entire file** if Selected export is empty.

**Could not write a PNG thumbnail / FFmpeg error.**  
Use 0.3.5 or newer. Capture still works when the scene is set to video output.

**Upload listing blocked for a paid price.**  
Connect Stripe on [polyassetvault.com](https://polyassetvault.com), then **Refresh account**. Until payouts are connected, only free listings (`0`) are allowed.

**Sync or List froze Blender.**  
Current releases run those jobs off the UI thread. Install the latest zip.

---

## Support

Product site: [polyassetvault.com](https://polyassetvault.com)  
Email: [contact@vassbrekke.no](mailto:contact@vassbrekke.no)  
Bugs in this addon: [GitHub Issues](https://github.com/Vassbrekke/polyassetvault-blender-addon/issues)

GitHub Issues are for the addon (install, Blender UI, listing upload from Blender). Account, billing, and payouts are handled on the website.

Security reports: see [SECURITY.md](SECURITY.md). Do not open a public issue for an unpatched vulnerability.

---

## License

GPL-2.0-or-later — required for Blender add-ons. See [LICENSE](LICENSE).

Copyright © 2026 [Vassbrekke AS](https://www.vassbrekke.no).

---

## Development

```bash
git clone https://github.com/Vassbrekke/polyassetvault-blender-addon.git
cd polyassetvault-blender-addon
python3 -m unittest discover -s tests -v
./pack.sh
```

`./pack.sh` writes `polyassetvault-blender.zip` next to this README. Pushing a version bump on `main` publishes a new GitHub Release zip.

Local site/API overrides are only for people working on the PolyAssetVault stack. Production users should keep the default `https://polyassetvault.com` URLs.
