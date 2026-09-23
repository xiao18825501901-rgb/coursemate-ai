# LOGO ASSET MANIFEST

The owner supplied the final brand artwork in the revision of 2026-09-24. This document records what was
received, what was derived from it, and what was deliberately **not** done to it.

## 1. The source (kept read-only)

| | |
|---|---|
| Received as | `D:\UserData\Downloads\Codex 图像 2026年9月23日 01_20_02.png` |
| Stored in the repository as | `apps/web/brand-source/coursejesus-logo-source.png` |
| SHA-256 | `ae536df4cc1e9e989c3b9c7ff15a33137d1f526bcbc779aebd4b3e6e93be14e5` |
| Bytes | 610,482 |
| Format | PNG, RGBA (transparency), 1254×1254 |
| Ink bounding box | `(49, 19, 1216, 1214)` — the artwork itself is 1167×1195 |
| Dominant colour | `rgb(110, 0, 14)` — a deep crimson, which is now the manifest's `theme_color` |

**Not shipped to browsers.** `public/` is copied verbatim into the build, so the original and the
derivation record live in `apps/web/brand-source/` instead: they belong in Git as provenance, not in the
payload every visitor downloads. A test pins that split
(`services/rag-api/tests/test_brand_assets.py::test_the_provenance_files_are_not_shipped_to_browsers`).

## 2. How the appearance was established

This round's model cannot view images. The artwork was therefore read by measurement rather than by eye:
the alpha bounding box above, the colour histogram, and a coarse ink map of the alpha channel (printed by
`work/current-change/measure-logo.py`) which shows a roughly circular emblem with an internal design and
a crown-like upper section. Every derived file is verified against those measurements — a claim about
appearance that nobody checked visually is labelled as such rather than asserted.

## 3. What was derived

All derivations are deterministic and repeatable (`work/current-change/derive-logo-assets.py`): trim to
the ink bounding box, add a **uniform 4% margin** so the mark is centred at every size, resize with
LANCZOS, and for the platform-install icons composite onto the manifest's own `background_color`
(`#fffdf7`) because those platforms expect an opaque tile.

| File | Size | Opaque | Bytes | SHA-256 (first 16) |
|---|---|---|---|---|
| `logo-mark-512.png` | 512×512 | no | 135,714 | `89627f908028b6a6` |
| `favicon-48.png` | 48×48 | no | 3,500 | see `derived-manifest.json` |
| `favicon-32.png` | 32×32 | no | 1,884 | see `derived-manifest.json` |
| `favicon-16.png` | 16×16 | no | 662 | see `derived-manifest.json` |
| `apple-touch-icon-180.png` | 180×180 | yes | 30,690 | see `derived-manifest.json` |
| `icon-192.png` | 192×192 | yes | 33,861 | see `derived-manifest.json` |
| `icon-512.png` | 512×512 | yes | 143,113 | see `derived-manifest.json` |

The exact hashes are written beside the files in `apps/web/brand-source/derived-manifest.json`, and the
guard re-computes them. Two derivation defects were caught by that guard while it was being written: the
first attempt `paste`d with the mark as a mask, which left the install icons *semi-transparent* (alpha
191 of 255), and the second `paste`d without a mask, which left them fully transparent; the icons are now
composited with `alpha_composite` over an opaque base, and the guard asserts `alpha_min == 255` for every
opaque asset and `< 255` for the favicons.

## 4. What was deliberately not done

* **No regeneration.** The artwork is the owner's file, byte for byte; no image model was used to redraw,
  restyle or "improve" it.
* **No recolouring and no cropping of content.** The only geometric operation is a trim to the artwork's
  own alpha bounding box plus a uniform margin.
* **No stretching.** Every derived file is square, and a test asserts the trimmed source is square within
  5% before any resize, so a distorted mark cannot be shipped quietly.
* **No vector claim.** The icons are declared `image/png`. The interim mark was declared
  `image/svg+xml`; describing raster artwork as vector would be false.
* **No horizontal wordmark.** The source is a square emblem, so the navigation keeps the product name as
  text beside the mark instead of inventing a lockup the owner did not supply.

## 5. Where the mark is used

From the one brand source (`apps/web/src/brand.ts`), so no page hard-codes a path:

| Surface | File |
|---|---|
| Global navigation | `apps/web/src/ui/App.jsx` (`nav.global-nav .brand`) |
| Loading screen ("正在连接 …") | `apps/web/src/ui/App.jsx` |
| Sign-in card | `apps/web/src/ui/App.jsx` |
| Help drawer | `apps/web/src/ui/App.jsx` |
| Legacy shell header | `apps/web/src/components/Layout.tsx` |
| Document entries (favicons, apple-touch) | `%BRAND_ICONS%` in `apps/web/index.html`, `apps/web/ui.html`, filled by `apps/web/vite.config.ts` |
| Installable manifest icons | `apps/web/vite.config.ts::brandManifest` |

`themeColor` moved from the placeholder green `#0d4637` to the artwork's own `#6e000e`, so the browser
chrome no longer clashes with the mark.

## 6. Evidence

* `work/current-change/brand-journey-r82c.log` — the browser journey: the shipped shell serves
  `/brand/logo-mark-512.png` in the loading screen and the navigation, natural size 512×512, square at
  every instance, accurate alternative text, light and dark, at 1440px and 390px, with screenshots
  written to the Playwright output directory.
* `services/rag-api/tests/test_brand_assets.py` — six checks over the files: the original's hash, every
  derived file's size and hash, the preserved aspect ratio, the opaque/transparent split, the
  provenance-versus-served split, and agreement between `brand.ts` and the derivation record.
* `apps/web/tests/brand.test.ts` — the brand source declares the final artwork and both icon sets.

**Honest limit:** no human has looked at the rendered mark in this round, and this model cannot. The
screenshots exist for that review; everything above is measurement, not visual confirmation.
