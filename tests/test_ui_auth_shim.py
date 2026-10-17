"""Drift guards for the access-token shim inside BOTH consoles.

The access guard (``src/security/access.py``) gates every mutating request with
``X-Auth-Token``. The consoles are plain HTML, so when the guard is switched on
they would 401 on every save unless a shim attaches the header. The shim must:

* stay a strict no-op when no token is stored (auth-off is the default),
* bootstrap from ``/?token=XXX`` and then scrub the token out of the URL,
* cover ``fetch`` AND ``XMLHttpRequest`` (both consoles use plain ``fetch``, but
  the header must be attached whatever transport a caller picks),
* be valid JavaScript — proven behaviourally, not by grep.

``web/unified_ui.html`` is served by the engine, ``index.html`` by the
workbench — both sit behind the same gateway middleware, so both need the shim.
Stdlib-only, so it runs in the phone gate.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONSOLES = {
    "workbench": ROOT / "index.html",
    "engine": ROOT / "web" / "unified_ui.html",
}
TOKEN = "tok-" + "1" * 40


@pytest.fixture(params=sorted(CONSOLES), scope="module")
def page(request: pytest.FixtureRequest) -> tuple[str, str]:
    """(name, html) for each console, so both are checked identically."""
    name = request.param
    return name, CONSOLES[name].read_text(encoding="utf-8")


def _shim(html: str) -> str:
    """The shim's inline script body (between its markers)."""
    start = html.index("<script>\n(function(){") + len("<script>\n")
    return html[start:html.index("</script>", start)]


# ── source-level contract ────────────────────────────────────────────────
def test_shim_is_present_once(page: tuple[str, str]) -> None:
    """Exactly one shim per page — a duplicate would double-wrap ``fetch``."""
    _, html = page
    assert html.count("window.__nexusAuth") == 1
    assert html.count("nexus_auth_token") == 1


def test_shim_is_a_noop_without_a_token(page: tuple[str, str]) -> None:
    """Auth-off stays the default: no stored token ⇒ return before wrapping."""
    _, html = page
    assert 'localStorage.getItem(K)||""' in html
    assert "if(!tok)return;" in html


def test_shim_bootstraps_from_the_query_and_scrubs_it(
    page: tuple[str, str],
) -> None:
    """``/?token=XXX`` stores the token once and removes it from the URL."""
    _, html = page
    assert 'u.searchParams.get("token")' in html
    assert "localStorage.setItem(K,q)" in html
    assert 'u.searchParams.delete("token")' in html
    assert "history.replaceState" in html


def test_shim_never_recurses(page: tuple[str, str]) -> None:
    """The original ``fetch`` is captured before the wrap (no recursion)."""
    _, html = page
    assert "of=window.fetch" in html
    assert "of.call(window,input,init)" in html


def test_shim_parses_as_javascript(page: tuple[str, str], tmp_path: Path) -> None:
    """A real JS parser, since hand-rolled bracket counting lies on regexes."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    _, html = page
    target = tmp_path / "shim.js"
    target.write_text(_shim(html), encoding="utf-8")
    proc = subprocess.run(
        [node, "--check", str(target)], capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr


# ── behaviour ────────────────────────────────────────────────────────────
_RUNNER = r"""
const fs = require("fs");
if (typeof Headers === "undefined" || typeof URL === "undefined") {
  console.log(JSON.stringify({skip: true}));
  process.exit(0);
}
global.window = global;
const box = {};
if (process.env.STORE_TOKEN) box.nexus_auth_token = process.env.STORE_TOKEN;
global.localStorage = {
  getItem: function (k) { return (k in box) ? box[k] : null; },
  setItem: function (k, v) { box[k] = String(v); },
};
global.location = { href: process.env.HREF };
global.history = {
  replaceState: function (s, t, url) { global.location.href = "http://127.0.0.1:8000" + url; },
};
const calls = [];
global.fetch = function (input, init) { calls.push([input, init]); return Promise.resolve({}); };
function XHR() { this._h = {}; }
XHR.prototype.open = function () { return "orig-open"; };
XHR.prototype.setRequestHeader = function (k, v) { this._h[k] = v; };
global.XMLHttpRequest = XHR;
eval(fs.readFileSync(process.argv[2], "utf8"));
(async function () {
  await window.fetch("/api/training/run",
    {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"});
  await window.fetch("/api/status");
  const x = new XMLHttpRequest();
  x.open("POST", "/whatever");
  const init = calls[0] ? calls[0][1] : undefined;
  let post = null;
  if (init && init.headers) { new Headers(init.headers).forEach(function (v, k) { post = post || (k === "x-auth-token" ? v : post); }); }
  const git = calls[1] ? calls[1][1] : undefined;
  console.log(JSON.stringify({
    ok: true,
    wrapped: global.__nexusAuth === true,
    post: post,
    get_init: git === undefined ? null : Object.keys(git),
    xhr_header: x._h["X-Auth-Token"] || null,
    stored: global.localStorage.getItem("nexus_auth_token"),
    href: global.location.href,
  }));
})();
"""

_TOK = "tok-" + ("1" * 40)


def _run_shim(
    html: str, *, href: str, store: str | None, tmp_path: Path,
) -> dict:
    """Execute the shim in node with DOM stubs and report what it did."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    shim = tmp_path / "shim.js"
    shim.write_text(_shim(html), encoding="utf-8")
    runner = tmp_path / "runner.js"
    runner.write_text(_RUNNER, encoding="utf-8")
    env = {**os.environ, "HREF": href}
    if store is not None:
        env["STORE_TOKEN"] = store
    proc = subprocess.run(
        [node, str(runner), str(shim)], capture_output=True, text=True, env=env,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    if out.get("skip"):
        pytest.skip("node lacks Headers/URL")
    return out


def test_shim_attaches_the_token_to_writes_only(
    page: tuple[str, str], tmp_path: Path,
) -> None:
    """Behavioural proof: POST gains ``X-Auth-Token``, GET passes untouched."""
    _, html = page
    out = _run_shim(
        html, href="http://127.0.0.1:8000/", store=_TOK, tmp_path=tmp_path,
    )
    assert out["wrapped"] is True
    assert out["post"] == _TOK
    assert out["xhr_header"] == _TOK
    assert out["get_init"] is None  # GET never gained a header bag


def test_shim_bootstraps_the_token_from_the_url(
    html: str, tmp_path: Path,
) -> None:
    """``/?token=XXX`` is stored once, then scrubbed from the address bar."""
    out = _run_shim(
        html, href="http://127.0.0.1:8000/console?token=abc123",
        store=None, tmp_path=tmp_path,
    )
    assert out["stored"] == "abc123"
    assert "token=" not in out["href"]
    assert out["href"].endswith("/console")


@pytest.fixture(scope="module")
def html() -> str:
    """The engine console (the richest page) for the single-page checks."""
    return CONSOLES["engine"].read_text(encoding="utf-8")
