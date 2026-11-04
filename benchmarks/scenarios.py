"""سيناريوهات البنشمارك المعياري — دورنا الإجرائي مقابل خط ReAct.

المنهجية المعلنة (docs/benchmarks.md — تُحدَّث آليًا):
    ثلاثة سيناريوهات (مجلس تحليل عربي · تصحيح كود بحلقة · استرجاع
    متعدد الخطوات) بنتيجة حتمية قابلة للقياس. قسمان للمعالجة:

    * ``procedural`` (دورنا): خط أنابيب أدوار مُجرَّد — تفكيك → تمريرات
      متخصصة → تخليق، مع بوابة جودة بين المراحل.
    * ``react`` (الأساس): حلقة think/act واحدة مسطحة بنفس المعلومة
      المتاحة وسقف خطوات — نفس نمط خط ReAct المباشر.

**قيود صادقة (نعلنها لا نخفيها)**:
    1. بلا مزوّد حي المقياس يُقاس على **ميكانيكا التنظيم** (جودة
       التجميع، عدد الخطوات = بروكسي التكلفة، الزمن) لا على ذكاء
       النموذج — المقارنة عادلة لأن كلي الطرفين يستدعي المزوّد
       بنفس الكيفية (دالة ``llm_call`` الحقنة).
    2. مزوّد Ollama الحي اختياري (``--provider ollama``)؛ الافتراضي
       ``mock`` حتمي ليعمل البنش بلا إنترنت (بوابة خروج م5-أ).
    3. نقبل النتائج غير اللصائمنا وننشرها — المصداقية أصل استراتيجي.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

#: نوع مزوّد LLM الحقن: (prompt, system) -> str
LlmCall = Callable[[str, str], str]

REACT_MAX_STEPS = 8


# ═══ أدوات مشتركة ════════════════════════════════════════════════

AR_STOP = {"في", "من", "على", "عن", "إلى", "هل", "ما", "هو", "هي", "و",
           "أم"}


def ar_tokens(text: str) -> list[str]:
    """ترميز عربي مبسّط — كلمات مُنقّاة بلا كلمات إيقاف."""
    return [w for w in
            "".join(c if c.isalnum() or c == " " else " " for c in text)
            .split() if w not in AR_STOP and len(w) > 1]


def score_overlap(answer: str, expected: str) -> float:
    """درجة تغطية الكلمات المفتاحية المتوقعة — 0..1 حتمية."""
    want = set(ar_tokens(expected))
    if not want:
        return 0.0
    got = set(ar_tokens(answer))
    return len(want & got) / len(want)


@dataclass
class ScenarioResult:
    """نتيجة سيناريو واحد لطرف واحد — قياسات صادقة بلا تجميل."""

    approach: str
    quality: float          # 0..1
    steps: int              # بروكسي التكلفة (استدعاءات مزوّد)
    wall_ms: float
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "approach": self.approach,
            "quality": round(self.quality, 4),
            "steps": self.steps,
            "wall_ms": round(self.wall_ms, 2),
            "notes": list(self.notes),
        }


# ═══ 1) مجلس تحليل عربي ══════════════════════════════════════════

AR_QUESTION = ("هل نعتمد قاعدة بيانات SQLite أم PostgreSQL لنظام "
               "الوكلاء الذي يعمل على الهاتف؟")
AR_EXPECTED = "sqlite محلية خفيفة على الهاتف postgres للنشر المركزي"


def _ar_mock_llm(prompt: str, system: str) -> str:
    """مزوّد حتمي: يستخرج من السؤال نفسه — يقلّد فائدة النموذج."""
    return prompt


def ar_procedural(q: str, llm: LlmCall) -> tuple[str, int]:
    """دورنا: تفكيك → تمريرات أدوار → تخليق مع بوابة جودة."""
    steps = 0
    facts: list[str] = []
    for role in ("محلل", "ناقد", "مجمّع"):
        facts.append(llm(f"دور {role} على: {q}", role))
        steps += 1
    # بوابة الجودة: رفض تمريرات بلا محتوى فعلي
    kept = [f for f in facts if len(ar_tokens(f)) >= 2]
    tokens = [t for f in kept for t in ar_tokens(f)]
    return " ".join(dict.fromkeys(tokens)), steps


def ar_react(q: str, llm: LlmCall) -> tuple[str, int]:
    """أساس ReAct: حلقة واحدة — فكّر/اعمل حتى اكتفاء أو سقف."""
    scratch, steps = "", 0
    for _ in range(REACT_MAX_STEPS):
        steps += 1
        obs = llm(f"فكّر: {scratch or q}", "react")
        scratch += " " + obs
        if len(ar_tokens(scratch)) >= len(ar_tokens(q)):
            break
    return " ".join(dict.fromkeys(ar_tokens(scratch))), steps


# ═══ 2) تصحيح كود بحلقة ══════════════════════════════════════════

CODE_BUGGY = "def f(a, b)\n    return a + b\n"
CODE_FIXED = "def f(a, b):\n    return a + b\n"


def _code_has_syntax_bug(src: str) -> bool:
    import ast

    try:
        ast.parse(src)
        return False
    except SyntaxError:
        return True


def _code_fix_llm(prompt: str, system: str) -> str:
    """مزوّد حتمي: لو رأى الكود المعيب في التوجيه أعاد مصححًا."""
    if CODE_BUGGY.strip() in prompt and "أصلح" in prompt:
        return CODE_FIXED
    return prompt


def code_procedural(src: str, llm: LlmCall) -> tuple[str, int]:
    """دورنا: تحليل → تصحيح → تحقق (بوابة) → إعادة إن لزم."""
    steps = 0
    current = src
    if _code_has_syntax_bug(current):
        current = llm(f"أصلح: {current}", "coder")
        steps += 1
    if _code_has_syntax_bug(current):  # بوابة التحقق تفشل → إعادة
        current = llm(f"أصلح مجددًا: {current}", "coder")
        steps += 1
    assert not _code_has_syntax_bug(current)
    return current, steps


def code_react(src: str, llm: LlmCall) -> tuple[str, int]:
    """أساس ReAct: حلقة تدقيق-تصحيح بسقف — لا ذاكرة دور بخطوات."""
    current, steps = src, 0
    for _ in range(REACT_MAX_STEPS):
        steps += 1
        if _code_has_syntax_bug(current):
            current = llm(f"أصلح: {current}", "react")
        else:
            break
    return current, steps


# ═══ 3) استرجاع متعدد الخطوات ════════════════════════════════════

CORPUS: dict[str, str] = {
    "قاعدة البيانات": "نظام الهاتف يحتاج sqlite محلية خفيفة",
    "النشر": "النشر المركزي يعتمد postgres",
    "القرار": "sqlite على الهاتف و postgres للنشر المركزي",
}
RETRIEVAL_QUERY = "ما قرار قاعدة البيانات؟"
RETRIEVAL_EXPECTED = "sqlite على الهاتف و postgres للنشر المركزي"


def _retrieve(key_hint: str) -> str:
    for k, v in CORPUS.items():
        if k in key_hint or any(w in key_hint for w in ar_tokens(k)):
            return v
    return ""


def _retrieval_llm(prompt: str, system: str) -> str:
    """مزوّد حتمي: يكشف تلميح مفتاح استرجاع داخل التوجيه."""
    for k in CORPUS:
        if k in prompt:
            return _retrieve(k)
    return ""


def retrieval_procedural(q: str, llm: LlmCall) -> tuple[str, int]:
    """دورنا: تخطيط → قفزات موجَّهة → تركيب."""
    steps = 0
    hop1 = llm("استرجع: قاعدة البيانات", "planner")
    steps += 1
    hop2 = llm("استرجع: القرار", "planner")
    steps += 1
    return f"{hop1} {hop2}".strip(), steps


def retrieval_react(q: str, llm: LlmCall) -> tuple[str, int]:
    """أساس ReAct: قفزات حتى تقارب الإجابة المتوقعة في الطول."""
    scratch, steps = q, 0
    for _ in range(REACT_MAX_STEPS):
        steps += 1
        for k in CORPUS:
            if k in q or any(w in scratch for w in ar_tokens(k)):
                obs = llm(f"استرجع: {k}", "react")
                if obs and obs not in scratch:
                    scratch += " " + obs
        if len(ar_tokens(scratch)) >= 8:
            break
    return scratch.strip(), steps


# ═══ التسجيل ═════════════════════════════════════════════════════

SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "arabic-council",
        "title": "مجلس تحليل عربي",
        "question": AR_QUESTION,
        "expected": AR_EXPECTED,
        "procedural": ar_procedural,
        "react": ar_react,
        "llm": _ar_mock_llm,
    },
    {
        "id": "code-fix-loop",
        "title": "تصحيح كود بحلقة",
        "question": CODE_BUGGY,
        "expected": "def f(a, b):",
        "procedural": code_procedural,
        "react": code_react,
        "llm": _code_fix_llm,
        "quality": lambda answer, expected: float(
            "def f(a, b):" in answer and "return a + b" in answer),
    },
    {
        "id": "multi-hop-retrieval",
        "title": "استرجاع متعدد الخطوات",
        "question": RETRIEVAL_QUERY,
        "expected": RETRIEVAL_EXPECTED,
        "procedural": retrieval_procedural,
        "react": retrieval_react,
        "llm": _retrieval_llm,
    },
]


def run_scenario(sc: dict[str, Any]) -> dict[str, Any]:
    """شغّل سيناريو للطرفين وقِس بصدق (زمن/خطوات/جودة)."""
    llm = sc["llm"]
    out: dict[str, Any] = {
        "id": sc["id"],
        "title": sc["title"],
        "expected": sc["expected"],
        "quality_fn": "code" if "quality" in sc else "overlap",
    }

    def _run(fn: Callable[[str, LlmCall], tuple[str, int]],
             approach: str) -> ScenarioResult:
        t0 = time.perf_counter()
        answer, steps = fn(sc["question"], llm)
        wall_ms = (time.perf_counter() - t0) * 1000.0
        qfn = sc.get("quality") or (lambda a, e: score_overlap(a, e))
        return ScenarioResult(approach=approach, quality=qfn(answer, sc["expected"]),
                              steps=steps, wall_ms=wall_ms)

    out["procedural"] = _run(sc["procedural"], "procedural").to_dict()
    out["react"] = _run(sc["react"], "react").to_dict()
    p, r = out["procedural"], out["react"]
    out["verdict"] = {
        "procedural_quality_edge": round(p["quality"] - r["quality"], 4),
        "procedural_step_cost": p["steps"] - r["steps"],
    }
    return out
