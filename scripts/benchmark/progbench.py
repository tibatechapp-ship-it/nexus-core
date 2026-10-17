#!/usr/bin/env python3
"""progbench.py — قياس جدي لقدرة الوكلاء البرمجية (pass@1 حقيقي بلا تخمين).

Unlike ``agent-benchmark.sh`` (which only checks that a model *answered*), this
harness **executes** the agent's code against hidden tests and scores the result.
Three task families:

* ``exec``     — the agent writes a function; we import it and run asserts.
* ``mutation`` — the agent writes tests; we run them against a correct impl
                 (must all pass) and a buggy one (at least one must fail).
* ``keyword``  — the agent must identify a concept (checked by required terms).

Every call goes to a live gateway's ``POST /api/chat`` (SSE) honouring the
agent's own system prompt. Stdlib only — runs on the phone.

Usage::

    python3 scripts/benchmark/progbench.py                      # all agents, all tasks
    python3 scripts/benchmark/progbench.py --agents coder,tester --tasks gen_two_sum
    python3 scripts/benchmark/progbench.py --base-url http://127.0.0.1:8000 --limit 3
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

BENCH_DIR = Path(__file__).resolve().parent
REPO_ROOT = BENCH_DIR.parent.parent


# ═════════════════════════════════════════════════════════════════════════
# Task model + bank
# ═════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class Task:
    """مهمة قياس واحدة: مُوجَّه للوكيل + طريقة التصحيح."""

    id: str
    category: str
    kind: str  # "exec" | "mutation" | "keyword"
    prompt: str
    tests: str = ""                        # exec: تُنفَّذ في فضاء الدالة
    reference: str = ""                    # mutation: التنفيذ الصحيح
    mutant: str = ""                       # mutation: التنفيذ المعطوب
    checks: Tuple[Tuple[str, ...], ...] = ()  # keyword: كل مجموعة يجب أن تُصاب


_ASK_CODE = "\nأخرِج كتلة كود Python واحدة فقط (```python) ولا تُضِف شرحاً."

_TWO_SUM = """اكتب دالة Python باسم `two_sum(nums, target)` تُرجع فهرسي الرقمين
اللذين مجموعهما يساوي target (الحل مضمون الوجود). رتّب الفهرسين تصاعدياً إذا
أمكن.""" + _ASK_CODE

_PALINDROME = """اكتب دالة `is_palindrome(s)` تُرجع True إذا كانت السلسلة palindrome
بعد تجاهل حالة الأحرف والمسافات وعلامات الترقيم، مع دعم كامل لـ Unicode
(مثال: "A man, a plan, a canal: Panama" → True).""" + _ASK_CODE

_MERGE = """اكتب دالة `merge_intervals(intervals)` تدمج كل الفترات المتداخلة
وتُرجع قائمة مرتّبة بالفترات المدمجة. كل فترة قائمة [start, end].""" + _ASK_CODE

_LRU = """اكتب صنف `LRUCache(capacity)` يطبّق سياسة Least Recently Used مع
`get(key)` (تُرجع القيمة أو -1 إذا لم يوجد المفتاح) و`put(key, value)`.""" + _ASK_CODE

_BUGGY_BS = '''def binary_search(arr, target):
    lo, hi = 0, len(arr)
    while lo < hi:
        mid = (lo + hi) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            lo = mid
        else:
            hi = mid
    return -1'''

_DEBUG = """الدالة التالية فيها خطأ يجعلها تدخل حلقة لا نهائية على بعض المدخلات.
أصلحها وأخرِج الدالة المصحَّحة (نفس الاسم والتوقيع).

```python
""" + _BUGGY_BS + """
```

يجب أن تُرجع الدالة فهرس target في مصفوفة مرتّبة، أو -1 إذا لم يوجد.""" + _ASK_CODE

_SLUGIFY_REF = """import re
import unicodedata


def slugify(text):
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\\w\\s-]", "", text).strip().lower()
    return re.sub(r"[\\s_-]+", "-", text)
"""

_SLUGIFY_MUTANT = _SLUGIFY_REF.replace(
    're.sub(r"[\\s_-]+", "-", text)', 're.sub(r"[\\s_-]+", "_", text)'
)

_TESTS_TASK = """في الملف `solution.py` دالة `slugify(text)` تحوّل نصاً إلى slug.
اكتب دوال اختبار باسم يبدأ بـ `test_` تتحقّق من صحة `slugify` وتكتشف أي خطأ
محتمل فيها (اختبارات جيدة، لا مجرد assert صحيح دائماً). لا تُعِد كتابة الدالة،
فقط دوال الاختبار، في كتلة كود Python واحدة.""" 

_SQL_VULN = """راجع الكود التالي:

```python
@app.get("/user")
def get_user(name):
    cur.execute("SELECT * FROM users WHERE name = '" + name + "'")
    return cur.fetchone()
```

ما الثغرة الأمنية هنا؟ اذكر اسمها وكيفية إصلاحها بإيجاز."""

_GIT_TOOL = """كيف تجد — بأمر git — أيّ commit عدّل ملفاً معيّناً؟
اكتب الأمر الذي تستخدمه."""


TASK_BANK: Tuple[Task, ...] = (
    Task(
        id="gen_two_sum", category="codegen", kind="exec", prompt=_TWO_SUM,
        tests=(
            "def _norm(x):\n    return sorted(list(x))\n"
            "assert _norm(two_sum([2, 7, 11, 15], 9)) == [0, 1]\n"
            "assert _norm(two_sum([3, 2, 4], 6)) == [1, 2]\n"
            "assert _norm(two_sum([3, 3], 6)) == [0, 1]\n"
            "assert _norm(two_sum([-1, -2, -3, -4, -5], -8)) == [2, 4]\n"
        ),
    ),
    Task(
        id="gen_palindrome", category="codegen", kind="exec", prompt=_PALINDROME,
        tests=(
            "assert is_palindrome('A man, a plan, a canal: Panama')\n"
            "assert is_palindrome(\"No 'x' in Nixon\")\n"
            "assert is_palindrome('')\n"
            "assert not is_palindrome('race a car')\n"
            "assert not is_palindrome('0P')\n"
        ),
    ),
    Task(
        id="gen_merge_intervals", category="codegen", kind="exec", prompt=_MERGE,
        tests=(
            "def _n(x):\n    return [list(t) for t in x]\n"
            "assert _n(merge_intervals([[1, 3], [2, 6], [8, 10], [15, 18]]))"
            " == [[1, 6], [8, 10], [15, 18]]\n"
            "assert _n(merge_intervals([[1, 4], [4, 5]])) == [[1, 5]]\n"
            "assert _n(merge_intervals([[1, 4], [0, 4]])) == [[0, 4]]\n"
            "assert _n(merge_intervals([])) == []\n"
        ),
    ),
    Task(
        id="gen_lru_cache", category="codegen", kind="exec", prompt=_LRU,
        tests=(
            "c = LRUCache(2)\n"
            "c.put(1, 1)\n"
            "c.put(2, 2)\n"
            "assert c.get(1) == 1\n"
            "c.put(3, 3)\n"
            "assert c.get(2) == -1\n"
            "c.put(4, 4)\n"
            "assert c.get(1) == -1\n"
            "assert c.get(3) == 3\n"
            "assert c.get(4) == 4\n"
        ),
    ),
    Task(
        id="debug_binary_search", category="debugging", kind="exec", prompt=_DEBUG,
        tests=(
            "assert binary_search([1, 3, 5, 7, 9, 11], 7) == 3\n"
            "assert binary_search([1, 3, 5, 7, 9, 11], 1) == 0\n"
            "assert binary_search([1, 3, 5, 7, 9, 11], 11) == 5\n"
            "assert binary_search([1, 3, 5, 7, 9, 11], 4) == -1\n"
            "assert binary_search([], 5) == -1\n"
        ),
    ),
    Task(
        id="tests_slugify", category="testing", kind="mutation", prompt=_TESTS_TASK,
        reference=_SLUGIFY_REF, mutant=_SLUGIFY_MUTANT,
    ),
    Task(
        id="review_sql_injection", category="security", kind="keyword", prompt=_SQL_VULN,
        checks=(
            ("sql injection", "injection", "حقن"),
            ("parameteriz", "placeholder", "prepared", "bind", "%s"),
        ),
    ),
    Task(
        id="tool_git_history", category="tooling", kind="keyword", prompt=_GIT_TOOL,
        checks=(
            ("git log",),
            ("--follow", "git blame", "-p", "--oneline", " -S", "--stat"),
        ),
    ),
)


# ═════════════════════════════════════════════════════════════════════════
# Extraction + grading (pure, unit-testable, no network)
# ═════════════════════════════════════════════════════════════════════════
_FENCE_RE = re.compile(r"```(?:python|py)?[ \t]*\r?\n(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_python(text: str) -> str:
    """آخر كتلة كود Python غير فارغة من رد الوكيل (وإلا الرد كاملاً)."""
    blocks = [b for b in _FENCE_RE.findall(text or "") if b.strip()]
    if blocks:
        return blocks[-1].strip()
    return (text or "").strip()


_GRADE_HEADER = (
    "import importlib.util\n"
    "spec = importlib.util.spec_from_file_location('solution', 'solution.py')\n"
    "m = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(m)\n"
    "_src = open('_tests.py', encoding='utf-8').read()\n"
    "exec(compile(_src, '_tests.py', 'exec'), m.__dict__)\n"
    "print('PASS')\n"
)

_MUT_HEADER = (
    "import importlib.util\n"
    "spec = importlib.util.spec_from_file_location('solution', 'solution.py')\n"
    "sol = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(sol)\n"
    "ns = dict(sol.__dict__)\n"
    "exec(compile(open('agent_tests.py', encoding='utf-8').read(),"
    " 'agent_tests.py', 'exec'), ns)\n"
    "ran = fails = 0\n"
    "for _n, _o in list(ns.items()):\n"
    "    if _n.startswith('test_') and callable(_o):\n"
    "        ran += 1\n"
    "        try:\n"
    "            _o()\n"
    "        except Exception:\n"
    "            fails += 1\n"
    "print('RAN=%d FAILS=%d' % (ran, fails))\n"
)


def _run_python(
    script: str,
    workdir: Path,
    files: Dict[str, str],
    timeout: float,
) -> Dict[str, Any]:
    """يشغّل سكربتاً داخل مجلد مؤقت معزول، ويرجع الخرج/المهلة."""
    for name, content in files.items():
        (workdir / name).write_text(content, encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, script],
            cwd=str(workdir),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "returncode": proc.returncode,
            "stdout": proc.stdout[-2000:],
            "stderr": proc.stderr[-2000:],
        }
    except subprocess.TimeoutExpired:
        return {"returncode": -9, "stdout": "", "stderr": "TIMEOUT"}


def grade_exec(code: str, tests: str, timeout: float = 20.0) -> Dict[str, Any]:
    """يشغّل كود الوكيل مقابل الاختبارات المخفية. ok = نجحت كل الـ asserts."""
    if not code.strip():
        return {"ok": False, "returncode": -1, "stdout": "", "stderr": "EMPTY"}
    with tempfile.TemporaryDirectory() as td:
        res = _run_python(
            "_grade.py",
            Path(td),
            {
                "solution.py": code + "\n",
                "_tests.py": tests + "\n",
                "_grade.py": _GRADE_HEADER,
            },
            timeout,
        )
    res["ok"] = res["returncode"] == 0 and "PASS" in res["stdout"]
    return res


def _mutation_counts(
    impl: str, agent_tests: str, timeout: float
) -> Optional[Tuple[int, int]]:
    with tempfile.TemporaryDirectory() as td:
        res = _run_python(
            "_mut.py",
            Path(td),
            {
                "solution.py": impl + "\n",
                "agent_tests.py": agent_tests + "\n",
                "_mut.py": _MUT_HEADER,
            },
            timeout,
        )
    m = re.search(r"RAN=(\d+) FAILS=(\d+)", res["stdout"])
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def grade_mutation(
    reference: str, mutant: str, agent_tests: str, timeout: float = 20.0
) -> Dict[str, Any]:
    """اختبارات الوكيل يجب أن تنجح على الصحيح وتفشل على المعطوب."""
    if not agent_tests.strip():
        return {"ok": False, "ref": None, "mut": None, "reason": "EMPTY"}
    if not re.search(r"def\s+test_\w+", agent_tests):
        return {"ok": False, "ref": None, "mut": None, "reason": "NO_TESTS"}
    ref = _mutation_counts(reference, agent_tests, timeout)
    mut = _mutation_counts(mutant, agent_tests, timeout)
    if ref is None or mut is None:
        return {"ok": False, "ref": ref, "mut": mut, "reason": "CRASH"}
    ref_ran, ref_fails = ref
    _mut_ran, mut_fails = mut
    ok = ref_ran >= 1 and ref_fails == 0 and mut_fails >= 1
    return {"ok": ok, "ref": ref, "mut": mut, "reason": ""}


def grade_keywords(
    response: str, checks: Sequence[Sequence[str]]
) -> Dict[str, Any]:
    """كل مجموعة كلمات يجب أن تُصاب (any-of داخل المجموعة)."""
    low = (response or "").lower()
    hits = [any(k.lower() in low for k in group) for group in checks]
    return {"ok": all(hits) and len(hits) > 0, "groups": hits}


def grade_task(task: Task, response_text: str, timeout: float = 20.0) -> Dict[str, Any]:
    """يوزّع على المُصحِّح المناسب حسب نوع المهمة."""
    code = extract_python(response_text)
    if task.kind == "exec":
        return grade_exec(code, task.tests, timeout)
    if task.kind == "mutation":
        return grade_mutation(task.reference, task.mutant, code, timeout)
    if task.kind == "keyword":
        return grade_keywords(response_text, task.checks)
    return {"ok": False, "reason": f"UNKNOWN_KIND:{task.kind}"}


# ═════════════════════════════════════════════════════════════════════════
# Live gateway client
# ═════════════════════════════════════════════════════════════════════════
def call_agent(
    base_url: str, agent: Optional[str], message: str, timeout: float = 90.0
) -> Dict[str, Any]:
    """يستدعي ``POST /api/chat`` (SSE) ويجمع نص الرد + المزود + المدة."""
    body = json.dumps({"message": message, "agent": agent}).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + "/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    chunks: List[str] = []
    provider = ""
    error = ""
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    d = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if d.get("type") == "chunk":
                    chunks.append(d.get("content", ""))
                    provider = d.get("provider", provider) or provider
                elif d.get("type") == "error":
                    error = d.get("content", "")
    except Exception as exc:  # network/HTTP failure — reported, not hidden
        error = f"{type(exc).__name__}: {exc}"
    return {
        "text": "".join(chunks),
        "provider": provider,
        "error": error,
        "elapsed": round(time.time() - t0, 2),
    }


def fetch_agents(base_url: str, timeout: float = 10.0) -> List[Dict[str, Any]]:
    """قائمة الوكلاء الحقيقيين من ``/api/agents``."""
    try:
        with urllib.request.urlopen(
            base_url.rstrip("/") + "/api/agents", timeout=timeout
        ) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return list(data.get("agents", []))
    except Exception:
        return []


# ═════════════════════════════════════════════════════════════════════════
# Runner + reporting
# ═════════════════════════════════════════════════════════════════════════
def run_benchmark(
    base_url: str,
    agent_ids: Sequence[str],
    tasks: Sequence[Task],
    *,
    timeout: float = 90.0,
    progress: bool = True,
) -> Dict[str, Any]:
    """يشغّل المصفوفة كاملة (وكيل × مهمة) ويرجع النتائج الخام."""
    results: List[Dict[str, Any]] = []
    started = time.time()
    for agent in agent_ids:
        for task in tasks:
            call = call_agent(base_url, agent, task.prompt, timeout)
            if call["text"]:
                grade = grade_task(task, call["text"])
            else:
                grade = {"ok": False, "reason": "NO_RESPONSE"}
            row = {
                "agent": agent,
                "task": task.id,
                "category": task.category,
                "ok": bool(grade.get("ok")),
                "provider": call["provider"],
                "elapsed": call["elapsed"],
                "error": call["error"],
                "grade": {k: v for k, v in grade.items() if k != "ok"},
            }
            results.append(row)
            if progress:
                mark = "PASS" if row["ok"] else "fail"
                print(
                    f"  [{mark}] {agent:16s} {task.id:22s} "
                    f"{call['elapsed']:5.1f}s {call['provider']}",
                    flush=True,
                )
        if progress:
            won = sum(1 for r in results if r["agent"] == agent and r["ok"])
            print(f"  → {agent}: {won}/{len(tasks)} pass@1\n", flush=True)
    return {
        "base_url": base_url,
        "started": started,
        "duration": round(time.time() - started, 1),
        "agents": list(agent_ids),
        "tasks": [t.id for t in tasks],
        "results": results,
    }


def summarize(raw: Dict[str, Any]) -> Dict[str, Any]:
    """يجمّع النتائج: pass@1 لكل وكيل ولكل مهمة + المتوسط الكلي."""
    results = raw["results"]
    per_agent: Dict[str, Dict[str, Any]] = {}
    per_task: Dict[str, Dict[str, Any]] = {}
    for row in results:
        a = per_agent.setdefault(row["agent"], {"pass": 0, "total": 0})
        a["total"] += 1
        a["pass"] += int(row["ok"])
        t = per_task.setdefault(row["task"], {"pass": 0, "total": 0})
        t["total"] += 1
        t["pass"] += int(row["ok"])
    for a in per_agent.values():
        a["pass_at_1"] = round(a["pass"] / a["total"], 4) if a["total"] else 0.0
    for t in per_task.values():
        t["pass_at_1"] = round(t["pass"] / t["total"], 4) if t["total"] else 0.0
    total = len(results)
    passed = sum(int(r["ok"]) for r in results)
    return {
        "overall_pass_at_1": round(passed / total, 4) if total else 0.0,
        "passed": passed,
        "total": total,
        "per_agent": per_agent,
        "per_task": per_task,
    }


def _bar(frac: float, width: int = 16) -> str:
    filled = int(round(frac * width))
    return "#" * filled + "." * (width - filled)


def render_markdown(raw: Dict[str, Any], summ: Dict[str, Any]) -> str:
    """تقرير Markdown مقروء (عربي/إنجليزي) يصلح للأرشفة."""
    lines: List[str] = []
    lines.append("# مقاييس قدرات الوكلاء البرمجية — progbench")
    lines.append("")
    lines.append(f"**الخادم:** {raw['base_url']}")
    lines.append(f"**المدة:** {raw['duration']}ث")
    lines.append(
        f"**الإجمالي:** {summ['passed']}/{summ['total']} "
        f"= **{summ['overall_pass_at_1'] * 100:.1f}%** pass@1"
    )
    lines.append("")
    lines.append("## pass@1 لكل وكيل")
    lines.append("")
    lines.append("| الوكيل | pass@1 | نجح/الكل |")
    lines.append("|---|---|---|")
    for agent, a in sorted(
        summ["per_agent"].items(), key=lambda kv: -kv[1]["pass_at_1"]
    ):
        lines.append(
            f"| {agent} | `{_bar(a['pass_at_1'])}` "
            f"{a['pass_at_1'] * 100:.0f}% | {a['pass']}/{a['total']} |"
        )
    lines.append("")
    lines.append("## pass@1 لكل مهمة")
    lines.append("")
    lines.append("| المهمة | النوع | pass@1 |")
    lines.append("|---|---|---|")
    kind_of = {t.id: t.kind for t in TASK_BANK}
    for task, t in sorted(summ["per_task"].items(), key=lambda kv: kv[1]["pass_at_1"]):
        lines.append(
            f"| {task} | {kind_of.get(task, '?')} | {t['pass_at_1'] * 100:.0f}% |"
        )
    lines.append("")
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="قياس قدرات الوكلاء البرمجية (pass@1).")
    p.add_argument("--base-url", default="http://127.0.0.1:8000")
    p.add_argument("--agents", default="", help="قائمة مفصولة بفواصل (افتراضياً: الكل)")
    p.add_argument("--tasks", default="", help="معرّفات مهام مفصولة بفواصل")
    p.add_argument("--limit", type=int, default=0, help="أول N وكيل فقط")
    p.add_argument("--timeout", type=float, default=90.0)
    p.add_argument("--out-dir", default=str(REPO_ROOT / "reports" / "benchmark"))
    p.add_argument("--quiet", action="store_true")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    available = fetch_agents(args.base_url)
    ids = [a["id"] for a in available] or ["coder", "tester", "reviewer", "debugger"]
    if args.agents:
        wanted = [x.strip() for x in args.agents.split(",") if x.strip()]
        ids = [i for i in wanted if not available or i in {a["id"] for a in available}]
    if args.tasks:
        wanted_tasks = {x.strip() for x in args.tasks.split(",") if x.strip()}
        tasks = [t for t in TASK_BANK if t.id in wanted_tasks]
    else:
        tasks = list(TASK_BANK)
    if args.limit > 0:
        ids = ids[: args.limit]
    if not ids or not tasks:
        print("لا يوجد وكلاء أو مهام للتشغيل.", file=sys.stderr)
        return 2

    print(
        f"progbench: {len(ids)} وكيل × {len(tasks)} مهمة = {len(ids) * len(tasks)} استدعاء",
        flush=True,
    )
    raw = run_benchmark(
        args.base_url, ids, tasks, timeout=args.timeout, progress=not args.quiet
    )
    summ = summarize(raw)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    (out_dir / f"progbench-{stamp}.json").write_text(
        json.dumps({"raw": raw, "summary": summ}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    report = render_markdown(raw, summ)
    (out_dir / f"progbench-{stamp}.md").write_text(report, encoding="utf-8")

    print("")
    print(report)
    print(f"\nالتقرير: {out_dir}/progbench-{stamp}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
