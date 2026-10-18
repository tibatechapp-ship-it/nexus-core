"""Drift guards for the Academy panel inside ``web/unified_ui.html``.

The UI is one self-contained HTML file: markup, styles and JS inline. Nothing
imports it, so a typo in a translation key or a renamed element id would only
show up in a browser. These tests parse the file and pin the contract:

* the Academy markup + topbar button exist (and stay wired in ``bind``),
* every translation key the file asks for exists in BOTH languages,
* the panel talks to the real training endpoints.

Stdlib-only, so it runs in the phone gate.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

UI = Path(__file__).resolve().parents[1] / "web" / "unified_ui.html"


@pytest.fixture(scope="module")
def html() -> str:
    """The whole UI document as text."""
    return UI.read_text(encoding="utf-8")


def _block(html: str, lang: str) -> str:
    """The ``lang`` object literal inside the ``I18N`` map."""
    opener = f"\n  {lang}:{{"
    start = html.index(opener) + len(opener)
    end = html.index("\n  en:{", start) if lang == "ar" else html.index("\n};", start)
    return html[start:end]


def _keys(block: str) -> set[str]:
    """Translation keys declared in an I18N block."""
    return set(re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*:", block))


def _wanted(html: str) -> set[str]:
    """Every translation key the file asks for by name."""
    static = set(re.findall(r'data-i18n="([^"]+)"', html))
    static |= set(re.findall(r'data-i18n-ph="([^"]+)"', html))
    static |= set(re.findall(r'\bt\("([A-Za-z_][A-Za-z0-9_]*)"\)', html))
    return static


# ── markup ───────────────────────────────────────────────────────────────
def test_academy_markup_and_button_exist(html: str) -> None:
    """The panel is reachable: topbar button + modal + the three tabs."""
    assert 'id="btnAcademy"' in html
    assert 'id="academyModal"' in html
    for tab in ("Stages", "Lessons", "Fitness"):
        assert f'id="acaTab{tab}"' in html
        assert f'id="aca{tab}"' in html
    assert 'id="acaEvolve"' in html
    assert 'id="acaAgent"' in html
    assert 'id="acaRefresh"' in html


def test_academy_is_bound_and_closed(html: str) -> None:
    """The button is wired in ``bind`` and the modal closes with the rest."""
    assert '$("btnAcademy").onclick=openAcademy' in html
    assert '$("acaEvolve").onclick=acaEvolve' in html
    assert '$("academyModal").classList.remove("show")' in html


def test_every_academy_tab_selects(html: str) -> None:
    """Each tab routes to its own render, through one selector."""
    for tab in ("stages", "lessons", "fitness"):
        assert f'acaSelectTab("{tab}")' in html


# ── translations ─────────────────────────────────────────────────────────
def test_every_requested_key_exists_in_both_languages(html: str) -> None:
    """A missing key would render as its raw name in one language only."""
    ar, en = _keys(_block(html, "ar")), _keys(_block(html, "en"))
    wanted = _wanted(html)
    assert wanted <= ar, sorted(wanted - ar)
    assert wanted <= en, sorted(wanted - en)


def test_both_languages_declare_the_same_keys(html: str) -> None:
    """Arabic and English stay in step (no half-translated panel)."""
    ar, en = _keys(_block(html, "ar")), _keys(_block(html, "en"))
    assert ar == en, sorted(ar ^ en)


# ── wiring ───────────────────────────────────────────────────────────────
def test_academy_uses_the_training_api(html: str) -> None:
    """The panel reads the real routes, never a guess."""
    assert 'training:"/api/training"' in html
    for suffix in ('"/status"', '"/agents"', '"/lessons"', '"/fitness"',
                   '"/evolve"', '"/plan/"'):
        assert f"API.training+{suffix}" in html


def test_academy_renders_each_tab(html: str) -> None:
    """All three renderers exist and are reachable from ``acaRender``."""
    for name in ("acaRenderStages", "acaRenderLessons", "acaRenderFitness"):
        assert f"async function {name}(" in html
        assert f"await {name}(box)" in html


def test_action_and_status_labels_are_translated(html: str) -> None:
    """Genome actions/statuses get human words, not raw enum values."""
    assert 't("apexAction_"' in html
    assert 't("fitnessStatus_"+s)' in html
    for action in ("observe", "promote", "keep", "retrain", "revise", "unknown"):
        assert f"apexAction_{action}:" in html
    for status in ("elite", "stable", "probationary"):
        assert f"fitnessStatus_{status}:" in html


def test_fitness_tab_shows_the_task_channel(html: str) -> None:
    """A fitness row paints BOTH channels: council judgements and real tasks.

    The task channel is what a framework agent feeds on every ``/api/chat``
    run, so the panel must render it (and say "no tasks" honestly instead of
    showing a neutral 50% as if the agent had been measured by tasks).
    """
    for name in ("acaJudgeLine", "acaTaskLine", "acaScore"):
        assert f"function {name}(" in html
    for key in ('t("judgements")', 't("tasks")', 't("acaEvidence")',
                't("acaNoTasks")', 't("acaAvgTime")', 't("acaLastTask")'):
        assert key in html
    for field in ("f.task_observations", "f.task_successes", "f.task_rate",
                  "f.task_duration_avg", "f.task_last_ok", "f.evidence"):
        assert field in html
    assert "acaJudgeLine(f)+'<br>'+acaTaskLine(f)" in html


def test_academy_js_parses_as_javascript(html: str, tmp_path: Path) -> None:
    """Feed the inline script to a real JS parser when one is available.

    Hand-rolled bracket counting lies on regex literals and template strings, so
    the honest check is the engine itself. Node is optional (skip when absent).
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = html[html.index("<script>\n\"use strict\"") + 8:]
    script = script[: script.rindex("</script>")]
    target = tmp_path / "ui.js"
    target.write_text(script, encoding="utf-8")
    proc = subprocess.run(
        [node, "--check", str(target)], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
