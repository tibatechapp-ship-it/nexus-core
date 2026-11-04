"""اختبارات البنشمارك المنشور القابل للتكرار — م5 (docs/V2_ROADMAP.md §7).

بوابة خروج م5-أ: ``scripts/run_benchmark.py`` يعمل بلا إنترنت ويولّد
تقريرًا كاملًا. المنهجية: سيناريوهات حتمية، قياس صادق (جودة/خطوات/زمن)
للطرفين — ونعلن ما لا نكسبه.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

from benchmarks.scenarios import (  # noqa: E402
    SCENARIOS,
    ar_procedural,
    ar_react,
    ar_tokens,
    code_procedural,
    code_react,
    run_scenario,
    score_overlap,
)


# ── المبادئ ──────────────────────────────────────────────────────────────────────


def test_ar_tokens_strips_stopwords() -> None:
    toks = ar_tokens("هل نستخدم SQLite أم PostgreSQL؟")
    assert "هل" not in toks and "أم" not in toks
    assert "sqlite" in [t.lower() for t in toks]


def test_score_overlap_bounds() -> None:
    assert score_overlap("sqlite محلية", "sqlite محلية") == 1.0
    assert score_overlap("لا علاقة", "sqlite محلية") == 0.0


# ── السيناريوهات الثلاثة حتمية — التكرار يطابق ──────────────────────────────────


@pytest.mark.parametrize("idx", range(len(SCENARIOS)))
def test_scenarios_are_deterministic(idx: int) -> None:
    sc = SCENARIOS[idx]
    first = run_scenario(sc)
    second = run_scenario(sc)
    assert first["procedural"]["quality"] == second["procedural"]["quality"]
    assert first["react"]["steps"] == second["react"]["steps"]
    assert first["verdict"] == second["verdict"]


def test_three_scenarios_declared() -> None:
    assert [s["id"] for s in SCENARIOS] == [
        "arabic-council", "code-fix-loop", "multi-hop-retrieval"]


def test_code_procedural_actually_fixes_syntax() -> None:
    fixed, steps = code_procedural("def f(a, b)\n    return a + b\n",
                                   SCENARIOS[1]["llm"])
    import ast

    ast.parse(fixed)  # صالح الآن
    assert steps <= 2


def test_react_baseline_has_step_cap() -> None:
    _, steps = code_react("def f(a, b)\n    return a + b\n",
                          SCENARIOS[1]["llm"])
    assert 1 <= steps <= 8  # سقف الحلقة معلن


def test_procedural_wins_multi_hop_retrieval_honestly() -> None:
    out = run_scenario(SCENARIOS[2])
    assert out["procedural"]["quality"] > out["react"]["quality"]


def test_ar_council_quality_measured_not_asserted() -> None:
    """صدق المنهجية: لا نؤكد أننا نكسب — نقيس وننشر (حتى التعادل)."""
    out = run_scenario(SCENARIOS[0])
    assert 0.0 <= out["procedural"]["quality"] <= 1.0
    assert 0.0 <= out["react"]["quality"] <= 1.0


# ── المُشغِّل — بلا إنترنت ويولّد تقريرًا كاملًا (بوابة م5-أ) ────────────────────


def test_runner_generates_full_report(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_benchmark.py")],
        capture_output=True, text=True, timeout=120, cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stderr
    assert (ROOT / "benchmarks" / "results.json").exists()
    assert (ROOT / "docs" / "benchmarks.md").exists()


def test_committed_results_schema_and_coverage() -> None:
    d = json.loads((ROOT / "benchmarks" / "results.json").read_text(
        encoding="utf-8"))
    assert d["schema"] == "nexus.benchmark/v1"
    assert d["provider"] in ("mock", "ollama")
    assert len(d["scenarios"]) == 3
    for sc in d["scenarios"]:
        assert {"quality", "steps", "wall_ms"} <= set(sc["procedural"])
        assert {"quality", "steps", "wall_ms"} <= set(sc["react"])
        assert "procedural_quality_edge" in sc["verdict"]


def test_committed_md_has_methodology_and_limits() -> None:
    md = (ROOT / "docs" / "benchmarks.md").read_text(encoding="utf-8")
    assert "المنهجية" in md and "القيود الصادقة" in md
    assert "mock" in md  # مزوّد التشغيل معلن


def test_honesty_line_in_md_declares_react_strengths() -> None:
    md = (ROOT / "docs" / "benchmarks.md").read_text(encoding="utf-8")
    assert "خط ReAct يكفي" in md  # نعلن ما لا نكسبه — درس §8-4
