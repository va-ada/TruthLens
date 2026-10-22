"""The shipped frontend is pre-built: no CDN scripts, no in-browser Babel, no inline scripts (CSP script-src 'self')."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
CDN_HOSTS = ["unpkg.com", "cdn.jsdelivr.net", "cdnjs.cloudflare.com", "cdn.tailwindcss.com"]


@pytest.mark.parametrize("host", CDN_HOSTS)
def test_index_html_loads_nothing_from_cdns(host):
    assert host not in HTML


def test_index_html_has_no_babel_and_no_inline_scripts():
    assert "text/babel" not in HTML
    scripts = re.findall(r"<script\b[^>]*>", HTML, re.IGNORECASE)
    assert scripts == ['<script src="/static/app.js" defer>']


def test_built_assets_exist_and_are_real():
    js, css = ROOT / "static" / "app.js", ROOT / "static" / "app.css"
    assert js.stat().st_size > 100_000 and css.stat().st_size > 5_000
    bundle = js.read_text(encoding="utf-8")
    assert "X-Client-Id" in bundle and "/api/verify" in bundle  # built from the current source
    for host in CDN_HOSTS:
        assert f"//{host}" not in bundle
    assert ".apogee-card" in css.read_text(encoding="utf-8")


def test_textures_are_local():
    for name in ["earth_atmos_2048.jpg", "earth_clouds_1024.png"]:
        assert (ROOT / "static" / "img" / name).stat().st_size > 10_000


@pytest.mark.skipif(not shutil.which("npm") or not (ROOT / "node_modules").exists(), reason="node toolchain not installed")
def test_build_is_reproducible():
    before = (ROOT / "static" / "app.js").read_bytes()
    subprocess.run(["npm", "run", "build:js", "--silent"], cwd=ROOT, check=True, capture_output=True)
    assert (ROOT / "static" / "app.js").read_bytes() == before, "static/app.js is stale: run `npm run build`"
