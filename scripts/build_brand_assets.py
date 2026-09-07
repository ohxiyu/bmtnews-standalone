"""Build the brand vectors from one master; raster/ZIP export is a separate step.

No application dependencies. --font is only needed to re-outline the wordmark
(requires fontTools); routine builds reuse the committed wordmark-path.svg.
"""
import argparse
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "docs/media-kit"
IMAGES = ROOT / "docs/assets/images"
BLUE, LIGHT, INK, DARK_BLUE = "#1d4c96", "#faf9f7", "#1b1b18", "#8fb0e6"
NS = {"s": "http://www.w3.org/2000/svg"}


def svg(width, height, content):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" aria-label="BMTNews">\n{content}\n</svg>\n')


def build(font=None):
    KIT.mkdir(parents=True, exist_ok=True)
    if font:
        from fontTools.ttLib import TTFont
        from fontTools.pens.svgPathPen import SVGPathPen
        from fontTools.pens.transformPen import TransformPen
        face = TTFont(font)
        glyphs, cmap = face.getGlyphSet(), face.getBestCmap()
        scale = 100 / face["head"].unitsPerEm
        pen, x = SVGPathPen(glyphs), 0
        for letter in "BMTNews":
            glyph = glyphs[cmap[ord(letter)]]
            glyph.draw(TransformPen(pen, (scale, 0, 0, -scale, x, 80)))
            x += glyph.width * scale
        word = svg(round(x, 3), 100, f'<path d="{pen.getCommands()}"/>')
        (ROOT / "brand/wordmark-path.svg").write_text(word)
    mark = ET.parse(ROOT / "brand/mark.svg").find("s:path", NS).attrib["d"]
    word = ET.parse(ROOT / "brand/wordmark-path.svg").find("s:path", NS).attrib["d"]

    def symbol(color, transform=""):
        return f'<path fill="{color}" fill-rule="evenodd" transform="{transform}" d="{mark}"/>'

    def lockup(mark_color, text_color):
        return (symbol(mark_color, "translate(20 24) scale(.25)") +
                f'<path fill="{text_color}" transform="translate(176 34)" d="{word}"/>')

    for name, color in [("blue", BLUE), ("dark", DARK_BLUE), ("black", INK), ("white", "#ffffff")]:
        (KIT / f"bmtnews-mark-{name}.svg").write_text(svg(512, 512, symbol(color)))
        text = "#e8e6e1" if name == "dark" else (INK if name == "blue" else color)
        (KIT / f"bmtnews-lockup-{name}.svg").write_text(svg(670, 176, lockup(color, text)))

    app = svg(512, 512, f'<rect width="512" height="512" rx="108" fill="{BLUE}"/>' +
              symbol("#ffffff", "translate(66.56 66.56) scale(.74)"))
    # All foreground points fit inside the maskable safe circle (r = 40%).
    maskable = svg(512, 512, f'<rect width="512" height="512" fill="{BLUE}"/>' +
                   symbol("#ffffff", "translate(102.4 102.4) scale(.6)"))
    apple = svg(512, 512, f'<rect width="512" height="512" fill="{BLUE}"/>' +
                symbol("#ffffff", "translate(66.56 66.56) scale(.74)"))
    (KIT / "bmtnews-app.svg").write_text(app)
    (KIT / "bmtnews-maskable.svg").write_text(maskable)
    (KIT / "bmtnews-apple.svg").write_text(apple)
    for name, content in [("app-icon.svg", app), ("app-icon-maskable.svg", maskable),
                          ("bmtnews-favicon-v1.svg", app)]:
        (IMAGES / name).write_text(content)
    social = svg(1200, 630, f'<rect width="1200" height="630" fill="{LIGHT}"/>' +
                 '<g transform="translate(100 180) scale(1.5)">' + lockup(BLUE, INK) + '</g>' +
                 '<path stroke="#e4e2dc" d="M100 482H1100"/>')
    (KIT / "bmtnews-social.svg").write_text(social)
    (IMAGES / "og-default.svg").write_text(social)
    # Inline mark: no image fetch, currentColor follows the exact site theme.
    include = ('<svg xmlns="http://www.w3.org/2000/svg" class="site-brand-mark" viewBox="0 0 512 512" width="26" height="26" '
               'aria-hidden="true" focusable="false">' + symbol("currentColor") + '</svg>\n')
    (ROOT / "docs/_includes/brand-mark.html").write_text(include)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", type=Path)
    parser.add_argument("--package", action="store_true", help="Package already-rendered assets")
    args = parser.parse_args()
    if args.package:
        files = [(p, p.name) for p in sorted(KIT.iterdir()) if p.suffix in {".svg", ".png", ".md"}]
        files += [(p, "icons/" + p.name) for p in sorted(IMAGES.glob("bmtnews-*v1.*"))]
        files += [(ROOT / "docs/favicon.ico", "icons/favicon.ico")]
        files += [(p, "source/" + p.name) for p in sorted((ROOT / "brand").iterdir()) if p.is_file()]
        with zipfile.ZipFile(KIT / "bmtnews-media-kit-v1.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for path, name in files:
                info = zipfile.ZipInfo(name, (2026, 9, 7, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, path.read_bytes())
    else:
        build(args.font)
