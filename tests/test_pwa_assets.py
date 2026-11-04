"""PWA contract tests: the NovaMind web platform is installable and honest.

The web platform ships a static shell (``src/novamind/web_platform/backend/
static/``). VISION_2026 names "installable PWA" as a flagship feature, and
a PWA that half-works is worse than none: a manifest the browser rejects,
icons that 404, or a service worker that caches API state all fail silently
on the user's phone. These tests pin the whole contract offline:

* the manifest parses, is valid, and matches the platform's Arabic-first
  RTL identity and its actual theme colors,
* every declared icon exists, is a real PNG (magic bytes + IHDR), and its
  pixel dimensions equal its declared ``sizes`` — no lying manifests,
* the service worker exists, caches the shell it claims, NEVER intercepts
  or caches ``/api/`` state, and versions its cache,
* ``index.html`` actually wires the three pieces together (manifest link,
  theme-color, apple-touch-icon, guarded SW registration).

PNG parsing is stdlib-only (struct over the chunk stream) so this runs
anywhere pytest runs — no PIL dependency in CI.
"""
from __future__ import annotations

import json
import re
import struct
from pathlib import Path

import pytest

_STATIC = (
    Path(__file__).resolve().parent.parent
    / "src" / "novamind" / "web_platform" / "backend" / "static"
)


@pytest.fixture(scope="module")
def static_dir() -> Path:
    assert _STATIC.is_dir(), "web platform static dir is missing"
    return _STATIC


@pytest.fixture(scope="module")
def manifest(static_dir: Path) -> dict:
    path = static_dir / "manifest.webmanifest"
    assert path.is_file(), "manifest.webmanifest is missing"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def sw_js(static_dir: Path) -> str:
    path = static_dir / "sw.js"
    assert path.is_file(), "sw.js is missing"
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def index_html(static_dir: Path) -> str:
    path = static_dir / "index.html"
    assert path.is_file(), "index.html is missing"
    return path.read_text(encoding="utf-8")


def _png_dimensions(data: bytes) -> tuple[int, int]:
    """Read width/height from PNG magic + IHDR, stdlib-only."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG file"
    assert data[12:16] == b"IHDR", "first chunk is not IHDR"
    width, height = struct.unpack(">II", data[16:24])
    return width, height


# ───────────────────────────── manifest validity ─────────────────────────────

def test_manifest_identity_is_arabic_first(manifest: dict) -> None:
    assert manifest["lang"] == "ar"
    assert manifest["dir"] == "rtl"
    assert manifest["name"].strip()
    assert manifest["short_name"].strip()
    assert len(manifest["short_name"]) <= 12, "short_name must fit a launcher label"


def test_manifest_display_and_colors_match_the_theme(manifest: dict) -> None:
    assert manifest["display"] == "standalone"
    assert manifest["background_color"].lower() == "#0d1117"
    assert manifest["theme_color"].lower() == "#0d1117"
    # the platform's CSS defines exactly this palette — keep the two honest
    css = (_STATIC / "index.html").read_text(encoding="utf-8")
    assert "--bg: #0d1117" in css, "manifest colors drifted from the real theme"


def test_manifest_start_url_resolves_inside_scope(manifest: dict) -> None:
    start = manifest["start_url"]
    scope = manifest.get("scope", "./")
    assert scope == "./"
    assert (static_dir_resolved := (_STATIC / start).resolve()).is_file(), (
        f"start_url {start!r} does not resolve to a real file"
    )
    assert str(static_dir_resolved).startswith(str(_STATIC.resolve()))


def test_manifest_declares_installable_icon_sizes(manifest: dict) -> None:
    icons = manifest["icons"]
    assert icons, "manifest must declare icons"
    sizes = {icon["sizes"] for icon in icons}
    assert "192x192" in sizes, "192px icon required for install prompt"
    assert "512x512" in sizes, "512px icon required for install prompt"
    for icon in icons:
        assert icon["type"] == "image/png"
        assert set(icon.get("purpose", "any").split()) <= {"any", "maskable"}


def test_every_manifest_icon_exists_with_true_dimensions(manifest: dict) -> None:
    for icon in manifest["icons"]:
        path = _STATIC / icon["src"]
        assert path.is_file(), f"icon {icon['src']} is declared but missing"
        width, height = _png_dimensions(path.read_bytes())
        declared = icon["sizes"].lower()
        assert declared == f"{width}x{height}", (
            f"{icon['src']}: manifest says {declared}, real PNG is {width}x{height}"
        )


def test_maskable_icon_has_an_opaque_full_bleed_canvas(manifest: dict) -> None:
    """A transparent maskable icon disappears under launcher masks.

    The 512px icon is declared maskable; its corners must therefore be
    opaque pixels of the background color (full-bleed canvas). Reading the
    corner alpha honestly means decoding IDAT — with zlib from stdlib that
    is a dozen lines, and it catches a transparent-canvas icon dead on.
    """
    maskable = [i for i in manifest["icons"] if "maskable" in i.get("purpose", "")]
    assert maskable, "no maskable icon declared"
    path = _STATIC / maskable[0]["src"]

    import zlib

    data = path.read_bytes()
    pos, idat, width, height = 8, b"", 0, 0
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        ctype = data[pos + 4 : pos + 8]
        payload = data[pos + 8 : pos + 8 + length]
        if ctype == b"IHDR":
            width, height = struct.unpack(">II", payload[:8])
        elif ctype == b"IDAT":
            idat += payload
        pos += 12 + length
    raw = zlib.decompress(idat)

    bpp = 4

    # Walk the whole image with unfiltering (Paeth etc.), then sample corners.
    def reconstruct() -> list[bytearray]:
        rows: list[bytearray] = []
        prev = bytearray(width * bpp)
        offset = 0
        for _ in range(height):
            ftype = raw[offset]
            line = bytearray(raw[offset + 1 : offset + 1 + width * bpp])
            offset += 1 + width * bpp
            for i in range(len(line)):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                if ftype == 1:
                    line[i] = (line[i] + a) & 0xFF
                elif ftype == 2:
                    line[i] = (line[i] + b) & 0xFF
                elif ftype == 3:
                    line[i] = (line[i] + (a + b) // 2) & 0xFF
                elif ftype == 4:
                    p = a + b - c
                    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                    line[i] = (line[i] + pr) & 0xFF
            rows.append(line)
            prev = line
        return rows

    rows = reconstruct()
    for (x, y) in {(0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)}:
        r, g, b, a = rows[y][x * bpp : x * bpp + bpp]
        assert a == 255, f"corner ({x},{y}) is transparent — maskable icon must be full-bleed"
        assert (r, g, b) == (13, 17, 23), (
            f"corner ({x},{y}) is {(r, g, b)} — expected the #0d1117 background"
        )


# ───────────────────────────── service worker ─────────────────────────────

def test_sw_registers_fetch_install_and_activate(sw_js: str) -> None:
    for hook in ("addEventListener('install'", "addEventListener('activate'", "addEventListener('fetch'"):
        assert hook in sw_js, f"service worker is missing the {hook} handler"


def test_sw_cache_is_versioned_and_precaches_the_shell(sw_js: str) -> None:
    assert re.search(r"CACHE_VERSION\s*=\s*'[^']+'", sw_js), "cache name must be versioned"
    match = re.search(r"SHELL_ASSETS\s*=\s*\[(.*?)\]", sw_js, re.DOTALL)
    assert match, "SHELL_ASSETS list is missing"
    assets = re.findall(r"'([^']+)'", match.group(1))
    assert "./index.html" in assets and "./manifest.webmanifest" in assets
    for asset in assets:
        if asset.endswith((".html", ".webmanifest", ".png")):
            assert (_STATIC / asset).is_file(), f"precached asset {asset} does not exist"


def test_sw_never_touches_api_state(sw_js: str) -> None:
    assert "/api/" in sw_js, "the API carve-out must be explicit in the worker"
    fetch_body = sw_js.split("addEventListener('fetch'", 1)[1]
    assert "request.method !== 'GET'" in fetch_body, "non-GET must pass through"
    assert "pathname.startsWith('/api/')" in fetch_body, "API calls must never be intercepted"


def test_sw_offline_degradation_is_honest(sw_js: str) -> None:
    assert "503" in sw_js, "offline fallback must be an explicit 503, not a hang"
    assert "offline" in sw_js


# ───────────────────────────── wiring in index.html ─────────────────────────────

def test_index_links_the_manifest_and_theme(index_html: str) -> None:
    assert '<link rel="manifest" href="manifest.webmanifest">' in index_html
    assert '<meta name="theme-color" content="#0d1117">' in index_html
    assert '<link rel="apple-touch-icon" href="icons/icon-512.png">' in index_html


def test_index_registers_the_sw_with_a_protocol_guard(index_html: str) -> None:
    assert "navigator.serviceWorker.register('sw.js'" in index_html
    assert "/^https?:$/.test(location.protocol)" in index_html, (
        "SW registration must be guarded to http/https (never file://)"
    )
    assert index_html.index("serviceWorker") > index_html.index("<body"), (
        "SW registration must live in the body scripts, not the head"
    )


def test_relative_paths_keep_the_pwa_portable(index_html: str) -> None:
    """The shell is served from arbitrary sub-paths — every PWA reference
    must be relative (no leading slash), or installs break under a mount."""
    for href in re.findall(r'(?:href|content)="(/[^"]*)"', index_html):
        if "http" in href:
            continue
        # absolute local paths are exactly what breaks scope-relative installs
        assert not href.startswith("/"), f"absolute path {href!r} breaks portable installs"
