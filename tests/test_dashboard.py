"""Tests for ``src/orchestrator/dashboard.py`` (v1.25.0).

``summarize`` is pure (a plain list in, a dict out) so most assertions need no
filesystem. One integration test records real rows through ``_metrics.record``
into a ``tmp_path`` file and renders the CLI output end to end.
"""
from __future__ import annotations

from src.orchestrator import _metrics, dashboard


def _row(**over):
    base = {
        "ok": True,
        "decomposed": False,
        "risk": "low",
        "jury_fired": False,
        "agents": [],
        "failed_agents": [],
        "n_subtasks": 0,
    }
    base.update(over)
    return base


# ── summarize (pure) ────────────────────────────────────────────────────────

def test_summarize_empty_is_a_complete_shape():
    s = dashboard.summarize([])
    assert s["total"] == 0
    assert s["decomposed"] == 0 and s["single"] == 0
    assert s["decomposed_ratio"] == 0.0
    assert s["risk"] == {"low": 0, "med": 0, "high": 0}
    assert s["high_ratio"] == 0.0
    assert s["failed_runs"] == 0
    assert s["run_failure_rate"] == 0.0
    assert s["jury_fired"] == 0 and s["jury_rate"] == 0.0
    assert s["top_agents"] == []
    assert s["failure_rates"] == {}
    assert s["avg_subtasks"] == 0.0


def test_summarize_counts_decomposition_risk_and_jury():
    rows = [
        _row(decomposed=True, risk="high", jury_fired=True, n_subtasks=2,
             agents=["coder", "tester"]),
        _row(decomposed=False, risk="low", agents=["coder"]),
    ]
    s = dashboard.summarize(rows)
    assert s["total"] == 2
    assert s["decomposed"] == 1 and s["single"] == 1
    assert s["decomposed_ratio"] == 0.5
    assert s["risk"]["high"] == 1 and s["risk"]["low"] == 1
    assert s["high_ratio"] == 0.5
    assert s["jury_fired"] == 1 and s["jury_rate"] == 0.5
    assert s["avg_subtasks"] == 1.0
    assert s["top_agents"][0] == ("coder", 2)


def test_summarize_ignores_an_unknown_risk_level():
    s = dashboard.summarize([_row(risk="weird")])
    # an unrecognised level is skipped, never crashes the summary
    assert s["risk"] == {"low": 0, "med": 0, "high": 0}
    assert s["total"] == 1


def test_summarize_tracks_agent_failures():
    rows = [
        _row(ok=False, agents=["coder"], failed_agents=["coder"]),
        _row(agents=["coder"]),
    ]
    s = dashboard.summarize(rows)
    assert s["failed_runs"] == 1
    assert s["run_failure_rate"] == 0.5
    assert s["failure_rates"] == {"coder": 0.5}


def test_summarize_top_agents_is_capped_at_five_and_sorted():
    rows = []
    for i in range(7):
        rows.append(_row(agents=[f"agent{i}"] * (7 - i)))
    s = dashboard.summarize(rows)
    assert len(s["top_agents"]) == 5
    # highest run count first
    counts = [c for _a, c in s["top_agents"]]
    assert counts == sorted(counts, reverse=True)


# ── render ──────────────────────────────────────────────────────────────────

def test_render_prints_the_five_required_metrics():
    s = dashboard.summarize([
        _row(decomposed=True, risk="high", jury_fired=True, n_subtasks=2,
             agents=["coder", "tester"]),
    ])
    text = dashboard.render(s)
    assert "executions" in text
    assert "decomposed" in text
    assert "low / med / high" in text
    assert "jury fired" in text
    assert "coder" in text and "fail=" in text


def test_render_handles_no_data():
    text = dashboard.render(dashboard.summarize([]))
    assert "no executions recorded yet" in text


# ── end-to-end via a real metrics file ──────────────────────────────────────

def test_cli_reads_the_configured_metrics_file(tmp_path, monkeypatch, capsys):
    path = tmp_path / "metrics.json"
    monkeypatch.setenv("NEXUS_METRICS_PATH", str(path))
    _metrics.record(request="write a sum fn and test it", ok=True,
                    decomposed=True, risk="med",
                    subtasks=[{"agent": "coder", "ok": True, "risk": "med"},
                              {"agent": "tester", "ok": True, "risk": "low"}])
    rc = dashboard.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Orchestrator Dashboard" in out
    assert "coder" in out and "tester" in out
    assert "executions        : 1" in out
