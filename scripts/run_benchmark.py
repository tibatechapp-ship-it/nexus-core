#!/usr/bin/env python3
"""البنشمارك المنشور القابل للتكرار — م5 (docs/V2_ROADMAP.md §7).

يعمل **بلا إنترنت** افتراضيًا (مزوّد mock حتمي — بوابة خروج م5-أ)،
ويدعم Ollama الحي عبر ``--provider ollama`` (urllib فقط — localhost
``http://127.0.0.1:11434/api/generate``).

الاستخدام::

    python3 scripts/run_benchmark.py                 # mock — كامل التقرير
    python3 scripts/run_benchmark.py --provider ollama --model llama3.2

المخرجات: ``benchmarks/results.json`` + ملخص يُحدَّث آليًا في
``docs/benchmarks.md`` (منهجية معلنة + قيود صادقة + ما لا نكسبه).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.scenarios import SCENARIOS, run_scenario  # noqa: E402

RESULTS_PATH = ROOT / "benchmarks" / "results.json"
DOC_PATH = ROOT / "docs" / "benchmarks.md"

_PROVIDER_NOTE = {
    "mock": "مزوّد حتمي (mock) — يقيس ميكانيكا التنظيم لا ذكاء النموذج؛ "
            "المقارنة عادلة لأن الطرفين يستدعيان المزوّد بنفس الكيفية.",
    "ollama": "مزوّد حي محلي Ollama — بلا إنترنت، بلا مفاتيح، بلا سحابة.",
}


def ollama_call(model: str, prompt: str, system: str) -> str:
    """استدعاء Ollama المحلي — urllib فقط، فشل صريح (بلا صمت)."""
    import urllib.request

    body = json.dumps({
        "model": model, "prompt": prompt, "system": system,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate", data=body,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return str(data.get("response", ""))


def build_llm(provider: str, model: str):
    from benchmarks.scenarios import LlmCall

    if provider == "ollama":
        return lambda prompt, system: ollama_call(model, prompt, system)
    # mock: كل سيناريو يحقن مزوّده الحتمي الخاص (SCENARIOS[i]["llm"]).
    return None


def render_md(results: dict, provider: str, model: str) -> str:
    """تقرير ماركداون يُولَّد آليًا — منهجية + جدول + قيود صادقة."""
    lines = [
        "# البنشمارك المنشور — دورنا الإجرائي مقابل خط ReAct",
        "",
        f"> **مولَّد آليًا** في {results['generated_at']} بواسطة "
        "`scripts/run_benchmark.py` — لا تُحرَّر يدويًا.",
        "",
        f"**المزوّد**: `{provider}`{' (`' + model + '`)' if model else ''} — "
        f"{_PROVIDER_NOTE[provider]}",
        "",
        "## المنهجية",
        "",
        "ثلاثة سيناريوهات معيارية حتمية النتيجة. القياس: **الجودة** "
        "(تغطية الإجابة المتوقعة — أو قبول AST للكود)، **الخطوات** "
        "(بروكسي التكلفة: عدد استدعاءات المزوّد)، **الزمن** "
        "(wall-clock لكل طرف). سقف حلقة ReAct = 8 خطوات.",
        "",
        "| السيناريو | جودة إجرائي | جودة ReAct | فرق الجودة | خطوات إجرائي | خطوات ReAct |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for sc in results["scenarios"]:
        p, r = sc["procedural"], sc["react"]
        lines.append(
            f"| {sc['title']} | {p['quality']:.2f} | {r['quality']:.2f} | "
            f"{sc['verdict']['procedural_quality_edge']:+.2f} | "
            f"{p['steps']} | {r['steps']} |")
    lines += [
        "",
        "## القيود الصادقة (نعلنها لا نخفيها)",
        "",
        "1. وضع `mock` يقيس **ميكانيكا التنظيم** (بنية التمريرات، "
        "البوابات، عدد الخطوات) — لا ذكاء النموذج؛ المقارنة عادلة "
        "لأن كلي الطرفين يستدعي المزوّد بنفس الكيفية.",
        "2. السيناريوهات حتمية النتيجة لإمكانية التكرار الدقيق — "
        "التكرارية فوق الإبهار.",
        "3. **نقبل النتائج غير اللصائمنا وننشرها** — خط ReAct يكفي "
        "لأخطاء بسيطة (تصحيح كود بأخطاء ميكانيكية)؛ قيمنا تظهر حيث "
        "تتعدد الأدوار والبوابات، ونعلن ذلك كما هو.",
        "4. Ollama الحي: الأرقام تختلف باختلاف النموذج/الجهاز — "
        "اعرض منهجيتك عند إعادة التشغيل.",
        "",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="بنشمارك م5 القابل للتكرار")
    parser.add_argument("--provider", choices=["mock", "ollama"],
                        default="mock")
    parser.add_argument("--model", default="llama3.2",
                        help="نموذج Ollama عند --provider ollama")
    args = parser.parse_args(argv)

    llm_override = build_llm(args.provider, args.model)
    scenarios_out = []
    for sc in SCENARIOS:
        if llm_override is not None:
            sc = {**sc, "llm": llm_override}
        scenarios_out.append(run_scenario(sc))

    results = {
        "schema": "nexus.benchmark/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "provider": args.provider,
        "model": args.model if args.provider == "ollama" else "",
        "scenarios": scenarios_out,
    }
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOC_PATH.write_text(
        render_md(results, args.provider, args.model), encoding="utf-8")

    # ملخص صادق للطرفية — بما فيه ما لا نكسبه.
    for sc in scenarios_out:
        p, r = sc["procedural"], sc["react"]
        edge = sc["verdict"]["procedural_quality_edge"]
        winner = "إجرائي" if edge > 0 else ("ReAct" if edge < 0 else "تعادل")
        print(f"{sc['title']}: جودة {p['quality']:.2f} مقابل "
              f"{r['quality']:.2f} ({winner}) · خطوات {p['steps']} مقابل "
              f"{r['steps']}")
    print(f"\nالنتائج: {RESULTS_PATH}")
    print(f"التقرير: {DOC_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
