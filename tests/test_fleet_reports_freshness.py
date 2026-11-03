"""إنذار التراجع (ب1.5 — v1.49.0): التقارير جزء من تعريف «الإصدار».

الفجوة ف5: التقارير نُشرت عند 1.47.0 وبقيت قديمة حتى جاء إصلاح يدوي.
هذا الاختبار يجعل التقارير القديمة **تفشل CI** بدل أن تُهدأ بصمت:
``summary.version`` في التقرير المعتمد يجب أن يطابق إصدار ``pyproject``
— أي رفع إصدار بلا تجديد التقارير = فشل، وأي تقارير قديمة = فشل.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "fleet_inventory.json"
LEADERBOARD = ROOT / "reports" / "agent_leaderboard.md"


def _repo_version() -> str:
    """إصدار المستودع من مصدر الحقيقة الوحيد ``pyproject.toml``."""
    import tomllib

    with open(ROOT / "pyproject.toml", "rb") as f:
        return str(tomllib.load(f)["project"]["version"])


def test_reports_exist_and_fresh_at_release() -> None:
    """التقارير المعتمدة موجودة وتطابق الإصدار الحالي (ب1.5)."""
    assert REPORT.is_file(), (
        "reports/fleet_inventory.json مفقود — جدّد بـ `python3 -m src.fleet.report --deep`"
    )
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    reported = payload.get("summary", {}).get("version")
    current = _repo_version()
    assert reported == current, (
        f"التقارير قديمة: نُشرت عند {reported!r} والإصدار الحالي "
        f"{current!r} — شغّل `python3 -m src.fleet.report --deep` "
        "وأدرج التجديد في PR الإصدار"
    )


def test_leaderboard_matches_release_truth() -> None:
    """لوحة الترتيب تحمل الإصدار الحالي وتوزيع طبقات غير منحل."""
    assert LEADERBOARD.is_file(), "agent_leaderboard.md مفقود — جدّد التقارير"
    md = LEADERBOARD.read_text(encoding="utf-8")
    current = _repo_version()
    assert f"`{current}`" in md, f"اللوحة لا تحمل الإصدار الحالي {current!r} — تقارير قديمة"
    assert "توزيع الطبقات" in md
    assert "fake-clock" in md  # نموذج القياس المعلن حاضر


def test_report_payload_carries_measurement_contract() -> None:
    """حقل القياس المعلن حاضر في التقرير المعتمد (ب1.2/ب1.3)."""
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    ranking = payload.get("ranking", [])
    assert len(ranking) == 106
    novamind = [r for r in ranking if r["framework"] == "novamind"]
    assert len(novamind) == 79
    unmeasured = [r["name"] for r in novamind if r.get("run_ms") is None]
    assert not unmeasured, (
        f"وكلاء novamind بلا run_ms في التقرير المعتمد: {unmeasured[:5]} — "
        "جدّد التقارير بـ `python3 -m src.fleet.report --deep`"
    )
    # الإشباع انتهى: درجات متمايزة لا 106×100.0 — ثلاث قيم بنيوية على
    # الأقل (مُقاس ملتزم / بناء فقط / غير مُقاس) وأربع مع البطيء المعلن
    scores = {r["score"] for r in ranking}
    assert len(scores) >= 3, f"الدرجات مشبعة في التقرير المعتمد: {len(scores)}"
