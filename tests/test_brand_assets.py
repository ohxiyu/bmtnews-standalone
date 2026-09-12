"""Brand identity and packaged-asset regression checks (stdlib only)."""
import json
import struct
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
IMAGES = DOCS / "assets/images"
NS = {"s": "http://www.w3.org/2000/svg"}


def test_generated_symbols_share_one_evenodd_master_and_exact_palette():
    master = ET.parse(ROOT / "brand/mark.svg").find("s:path", NS).attrib["d"]
    inline = ET.parse(DOCS / "_includes/brand-mark.html")
    assert inline.find("s:path", NS).attrib["d"] == master
    assert inline.getroot().attrib["aria-hidden"] == "true"
    master_parts = ET.parse(ROOT / "brand/mark.svg").findall("s:path", NS)
    assert len(master_parts) == 3
    assert [p.attrib["d"] for p in inline.findall("s:path", NS)] == [p.attrib["d"] for p in master_parts]
    assert master.count("A64 64") == 5
    assert "A32 32" in master
    assert master.count("A12 12") == 8
    for filename, color in [("blue", "#1d4c96"), ("dark", "#8fb0e6"),
                            ("black", "#1b1b18"), ("white", "#ffffff")]:
        path = ET.parse(DOCS / f"media-kit/bmtnews-mark-{filename}.svg").find("s:path", NS)
        assert path.attrib["d"] == master
        assert path.attrib["fill-rule"] == "evenodd"
        assert path.attrib["fill"] == color
        parts = ET.parse(DOCS / f"media-kit/bmtnews-mark-{filename}.svg").findall("s:path", NS)
        assert [p.attrib["d"] for p in parts] == [p.attrib["d"] for p in master_parts]
        assert parts[1].attrib["fill"] == ("none" if filename in {"black", "white"} else "#ffcc29")
        assert parts[2].attrib["fill"] == (color if filename in {"black", "white"} else "#1b1b18")
    for path in (DOCS / "media-kit").glob("*.svg"):
        text = path.read_text()
        assert "<text" not in text, "Media wordmarks must not depend on installed fonts"
        assert "Gradient" not in text and "<image" not in text and "<script" not in text


def test_pwa_uses_versioned_distinct_maskable_and_any_icons():
    manifest = json.loads((DOCS / "manifest.webmanifest").read_text())
    assert manifest["id"] == "/"  # Never create a new installed-app identity.
    by_purpose = {icon["purpose"]: icon for icon in manifest["icons"]}
    assert by_purpose["maskable"]["src"] != by_purpose["any"]["src"]
    for icon in manifest["icons"]:
        assert "-v2.png" in icon["src"]
        data = (DOCS / icon["src"].lstrip("/")).read_bytes()
        width, height = struct.unpack(">II", data[16:24])
        assert f"{width}x{height}" == icon["sizes"]
    masked = ET.parse(DOCS / "media-kit/bmtnews-maskable.svg")
    assert masked.find("s:rect", NS).attrib.get("rx", "0") == "0"
    assert masked.find("s:path", NS).attrib["transform"] == "translate(102.4 102.4) scale(.6)"
    assert struct.unpack(">II", (IMAGES / "bmtnews-apple-180-v2.png").read_bytes()[16:24]) == (180, 180)


def test_media_archive_is_complete_and_matches_committed_assets():
    with zipfile.ZipFile(DOCS / "media-kit/bmtnews-media-kit-v2.zip") as archive:
        assert archive.testzip() is None
        assert "README.md" in archive.namelist()
        assert "source/mark.svg" in archive.namelist()
        for path in (DOCS / "media-kit").iterdir():
            if path.suffix in {".svg", ".png", ".md"}:
                assert archive.read(path.name) == path.read_bytes()
        for path in IMAGES.glob("bmtnews-*v2.*"):
            assert archive.read("icons/" + path.name) == path.read_bytes()
        for path in (ROOT / "brand").iterdir():
            if path.is_file():
                assert archive.read("source/" + path.name) == path.read_bytes()


def test_headers_sharing_and_favicons_use_the_new_brand():
    layout = (DOCS / "_layouts/default.html").read_text()
    head = (DOCS / "_includes/head-custom.html").read_text()
    assert layout.count("include brand-mark.html") == 2  # Header + footer
    assert "bmtnews-social-v2.png" in layout
    assert "bmtnews-favicon-v2.svg" in head
    assert "bmtnews-apple-180-v2.png" in head
    assert "?v=brand-20260913" in head
    assert "media-kit/" in layout
    assert struct.unpack(">II", (IMAGES / "bmtnews-social-v2.png").read_bytes()[16:24]) == (1200, 630)
    assert struct.unpack("<HHH", (DOCS / "favicon.ico").read_bytes()[:6]) == (0, 1, 3)
    css = (DOCS / "assets/css/bmtnews-ui.css").read_text()
    assert "color: var(--accent)" in css.split(".site-brand-mark {", 1)[1].split("}", 1)[0]
    card = (DOCS / "assets/js/story-card.js").read_text()
    assert ".site-brand .site-brand-mark path" in card
    assert "new Path2D(mark.getAttribute('d'))" in card
    assert "marks.forEach" in card  # Canvas must include eye and pupil, not only body.
