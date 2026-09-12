# BMTNews brand source — v2 / 2026-09-13

Approved direction: rounded b-like news symbol, two negative-space news bars,
and the yellow circular detail inspired by the user's Rare Laboratory mark.
All five convex corners use radius 64 on the 512-unit grid; the concave shoulder
uses radius 32. Both news bars are 176 × 36 with radius 12. The eye and pupil
share center (380, 284), with radii 52 and 22. No approximate raster tracing.

- `mark.svg`: canonical 512 × 512 mark, body / eye / pupil paths.
- `wordmark-path.svg`: outlined BMTNews wordmark, no runtime font dependency.
- `LICENSE_LIBERATION.txt`: source typeface notice. Wordmark outlines were made
  from Liberation Sans Bold, distributed with pdfjs-dist; no font binary is shipped.
- Public SVG, PNG and ZIP deliverables live in `docs/media-kit/`.
- Platform-specific files and legacy-compatible aliases live in `docs/assets/images/`.

## Rebuild

Run from the repository root. These are optional design tools, not application
runtime dependencies. The Python vector/package steps use only the standard library.

```sh
python3 scripts/build_brand_assets.py
node scripts/render_brand_assets.mjs /absolute/path/to/installed/sharp
python3 scripts/build_brand_assets.py --package
```

To change the wordmark, use `build_brand_assets.py --font /path/to/LiberationSans-Bold.ttf`
in an environment with fontTools. Otherwise the committed outlined source is used.
The raster exporter uses sharp (initial release rendered with sharp 0.35.4).

The master paths generate the inline Jekyll include and all media symbols. The
story-card canvas reads all three inline paths. Do not hand-edit generated SVGs.
Black/white variants leave the eye ring transparent and match the pupil to the
body; color variants use #FFCC29 for the ring and #1B1B18 for the pupil.
Versioned v1 assets remain unchanged for old cached pages; v2 uses new URLs.
After changing CSS/JS, update both asset_version values and run the tests. For a
future icon revision use new versioned filenames and update manifest/head references;
never overwrite an immutable URL and assume existing installations refresh it.

Public application colors are controlled by the site's CSS tokens. The inline
body uses currentColor, with no external file request and no additional AI calls.
