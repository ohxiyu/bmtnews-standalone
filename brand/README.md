# BMTNews brand source — v1 / 2026-09-07

Approved direction: compact rounded editorial layers + quotation tail. The
headline slot is transparent negative space, not a second accent color.

- `mark.svg`: canonical 512 × 512 mark, a single even-odd path.
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

The master path generates the inline Jekyll include and all media symbols. The
story-card canvas reads the same inline path. Do not hand-edit generated SVGs.
After changing CSS/JS, update both asset_version values and run the tests. For a
future icon revision use new versioned filenames and update manifest/head references;
never overwrite an immutable URL and assume existing installations refresh it.

Public application colors are controlled by the site's CSS tokens. The inline
symbol uses currentColor, with no external file request and no additional AI calls.
