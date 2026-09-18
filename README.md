# PolyAssetVault for Blender

Browse, buy, import, and list 3D assets on [polyassetvault.com](https://polyassetvault.com) without leaving Blender.

The addon talks to your PolyAssetVault account in the browser. Checkout stays on the website — cards never enter Blender.

**Requires Blender 4.2 or newer** (including 5.2 LTS).

---

## Install

1. Download the zip from [Releases](https://github.com/N0L0g1c/polyassetvault-blender-addon/releases), or pack it here:

   ```bash
   ./pack.sh
   ```

   That writes `polyassetvault-blender.zip` next to this README. Pushing a version bump on `main` publishes a new GitHub Release zip.

2. In Blender: **Edit → Preferences → Get Extensions → Install from Disk…**  
   (older layouts: **Add-ons → Install…**)

3. Enable **PolyAssetVault**.

4. Open a **3D Viewport**, press **N**, and open the **PolyAssetVault** tab.

The sidebar only appears over a 3D View. It will not show in the Scripting console, Text Editor, or Outliner.

To update later: quit Blender, pack again, install the new zip. If enable fails after an update, delete the old copy first:

```bash
rm -rf ~/.config/blender/5.2/extensions/user_default/polyassetvault
```

Use your Blender version in that path (`4.2`, `5.2`, …). Then install from disk again and confirm the version in Preferences matches this release.

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
2. Log in on polyassetvault.com. The page sends a device token back to Blender.
3. You stay signed in for 30 days.

Set a **Download folder** on the Account tab if you want purchases somewhere specific, then **Save preferences now**. Blender on Windows often has Auto-Save Preferences off, so that button matters.

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

Select the objects you want to sell (or switch to **Entire file**).

1. Open the **List** tab — empty fields fill from the selection.
2. **Fill from scene** if you want a fresh read (title, tags, polys, size, UVs, PBR, rig, animation, engine, category).
3. Frame the asset. **Capture thumbnail** (3D Viewport or Camera render) or **Pick thumbnail**. You should see the PNG in the panel. Capture again after switching Viewport / Camera.
4. Set **price**, **license**, and **Draft / Published**. Draft is the safe default. Price is free (`0`) or at least `1.00`. Paid prices need Stripe connected on the website; without it the listing stays free.
5. Use **Existing tags** or the suggestion chips so spellings match the catalog.
6. **Upload listing**.

The PNG is sent first (that is the catalog thumbnail), then the `.blend`. Upload refuses to continue without a real PNG. After a successful list, **Open on site** to review.

You still choose price, license, and whether it goes live. Everything else is filled from the scene so you do not have to re-enter it on the website.

---

## Preferences

**Edit → Preferences → Add-ons → PolyAssetVault**, or **Account → All settings**.

| Setting | Default |
| --- | --- |
| Site URL | `https://polyassetvault.com` |
| API base | `https://polyassetvault.com` |
| Download folder | Blender’s data files (`polyassetvault/library`) |

Use **Save preferences now** after changing the download folder.

Local development only: site `http://localhost:5173`, API `http://localhost:5000`.

---

## Troubleshooting

**I don’t see the tab.**  
Mouse over a 3D Viewport and press **N**. Layout workspace is easier than Scripting. Confirm the add-on is enabled.

**Enable error after an update.**  
Quit Blender, remove `~/.config/blender/<version>/extensions/user_default/polyassetvault`, pack, install from disk. Mixed old/new files from a previous zip will fail to load.

**Library previews are missing.**  
Sync again on 0.3.0 or newer. Thumbnails come from the marketplace listing, not a headless OpenGL render.

**Sidebar thumbnail didn’t change after recapture.**  
Capture again on 0.3.3 or newer. Switch to **Camera render** if the viewport capture looks too small.

**Listing has no picture on the site.**  
Capture or pick a PNG *before* upload. If the first file is the `.blend`, the site treats that as the thumbnail.

**Listing has no `.blend`.**  
Use **Entire file** if Selected export is empty. Reinstall 0.3.3+ if an older zip dropped the blend.

**Sync or List froze Blender.**  
0.2.2+ runs those jobs off the UI thread. Update if you are still on an older zip.

---

## License

GPL-2.0-or-later — required for Blender add-ons. See [LICENSE](LICENSE).

Maintained by [Vassbrekke AS](https://polyassetvault.com).
