"""Task catalog for the internal eval suite — 50 tasks, four categories.

كتالوج مهام التقييم الداخلي (مهمة M3.2): 50 مهمة موزعة على إنشاء تطبيق
وإصلاح عيب وكتابة اختبار وتحسين توثيق. كل مهمة تحمل بذوراً (ملفات ابتدائية
تُكتب في مجلد العمل المعزول) وملف تحقق pytest يفشل قبل الحل وينجح بعده، إضافة
إلى خطوات حل مرجعية تُستخدم ك oracle لموصل بلا شبكة وللتحقق من صلاحية الخطط.

العقد:
  * كل مهمة معزولة في مجلد عمل خاص — لا تلمس المستودع الحقيقي أبداً.
  * الهدف يبدأ بوسم ``[category-NN]`` ليقرأه البشر ويفهرسه التقرير.
  * الحل المرجعي يمر عبر نفس عقد ``RepairPlan`` (plan_from_json + validate)
    فلا يمكن أن يكون الحل المرجعي نفسه خطة غير صالحة.
"""

from __future__ import annotations

from dataclasses import dataclass

CATEGORIES: tuple[str, ...] = ("create", "fix", "test", "docs")

#: عدد المهام في كل فئة — المجموع 50 (بند قبول M3.2).
COUNTS: dict[str, int] = {"create": 12, "fix": 16, "test": 12, "docs": 10}

LOW = "low"


@dataclass(frozen=True)
class Task:
    """One eval task: seed files, expectations, and a reference solution."""

    id: str
    category: str
    goal: str
    seed: dict[str, str]
    expect: tuple[str, ...]
    solution_steps: tuple[dict, ...]
    tests_to_run: tuple[str, ...] = ("test_task.py",)


def _create_test(mod: str, fn: str, asserts: list[str]) -> str:
    body = "\n".join(f"    {a}" for a in asserts)
    return f"from {mod} import {fn}\n\n\ndef test_{fn}() -> None:\n{body}\n"


def _docs_test(keyword: str) -> str:
    return (
        "from pathlib import Path\n\n\n"
        f"KEYWORD = {keyword!r}\n\n\n"
        "def test_readme_has_section() -> None:\n"
        "    text = Path('README.md').read_text(encoding='utf-8')\n"
        "    assert KEYWORD in text\n"
    )


def _calc_fn_name(name: str, buggy: str) -> str:
    """Extract the function name from the buggy source (keeps variants DRY)."""
    for line in buggy.splitlines():
        if line.startswith("def "):
            return line[4:].split("(")[0].strip()
    raise ValueError(f"no def in variant {name}")


def _create_tasks() -> tuple[Task, ...]:
    """12 tasks: a module is missing; the verifier test must turn green."""
    variants: list[tuple[str, str, list[str]]] = [
        ("add_two", "def add_two(a, b):\n    return a + b\n",
         ["assert add_two(2, 3) == 5", "assert add_two(-1, 1) == 0"]),
        ("mul_two", "def mul_two(a, b):\n    return a * b\n",
         ["assert mul_two(3, 4) == 12", "assert mul_two(0, 9) == 0"]),
        ("square", "def square(x):\n    return x * x\n",
         ["assert square(7) == 49", "assert square(-3) == 9"]),
        ("is_positive", "def is_positive(x):\n    return x > 0\n",
         ["assert is_positive(2) is True", "assert is_positive(-2) is False"]),
        ("greet", 'def greet(name):\n    return f"مرحباً {name}"\n',
         ['assert greet("سالم") == "مرحباً سالم"']),
        ("biggest", "def biggest(a, b, c):\n    return max(a, b, c)\n",
         ["assert biggest(1, 9, 4) == 9", "assert biggest(5, 5, 5) == 5"]),
        ("half", "def half(x):\n    return x / 2\n",
         ["assert half(9) == 4.5"]),
        ("rev", "def rev(s):\n    return s[::-1]\n",
         ['assert rev("abc") == "cba"']),
        ("dup", "def dup(s):\n    return s * 2\n",
         ['assert dup("ab") == "abab"']),
        ("head", "def head(xs):\n    return xs[0]\n",
         ["assert head([7, 8, 9]) == 7"]),
        ("total_list", "def total_list(xs):\n    return sum(xs)\n",
         ["assert total_list([1, 2, 3]) == 6", "assert total_list([]) == 0"]),
        ("clamp01", "def clamp01(x):\n    return max(0, min(1, x))\n",
         ["assert clamp01(5) == 1", "assert clamp01(-5) == 0",
          "assert clamp01(0.5) == 0.5"]),
    ]
    out: list[Task] = []
    for i, (fn, code, asserts) in enumerate(variants, start=1):
        tid = f"create-{i:02d}"
        mod = f"mod_{i:02d}"
        out.append(Task(
            id=tid, category="create",
            goal=(f"[{tid}] أنشئ وحدة باسم {mod}.py تحتوي الدالة {fn} بحيث "
                  f"يمر ملف test_task.py الموجود دون أي تعديل عليه."),
            seed={"test_task.py": _create_test(mod, fn, asserts)},
            expect=(f"{mod}.py",),
            solution_steps=({
                "file": f"{mod}.py", "action": "create", "risk": LOW,
                "reason": f"الوحدة {mod} مطلوبة ليمر اختبار التحقق",
                "patch_hint": code,
            },),
        ))
    return tuple(out)


def _fix_tasks() -> tuple[Task, ...]:
    """16 tasks: calc.py holds a buggy function; the verifier fails now."""
    variants: list[tuple[str, str, str, list[str]]] = [
        ("op", "def calc(a, b):\n    return a - b\n",
         "def calc(a, b):\n    return a + b\n",
         ["assert calc(2, 3) == 5"]),
        ("off_by_one", "def total(n):\n    s = 0\n    for i in range(n):\n"
                       "        s += i\n    return s\n",
         "def total(n):\n    s = 0\n    for i in range(n + 1):\n"
         "        s += i\n    return s\n",
         ["assert total(4) == 10"]),
        ("const", "def c_to_f(c):\n    return c * 2 + 32\n",
         "def c_to_f(c):\n    return c * 9 / 5 + 32\n",
         ["assert c_to_f(100) == 212.0"]),
        ("inverted", "def is_even(n):\n    return n % 2 == 1\n",
         "def is_even(n):\n    return n % 2 == 0\n",
         ["assert is_even(4) is True", "assert is_even(5) is False"]),
        ("default", "def pow2(x, p=3):\n    return x ** p\n",
         "def pow2(x, p=2):\n    return x ** p\n",
         ["assert pow2(5) == 25", "assert pow2(3, 3) == 27"]),
        ("case", 'def shout(s):\n    return s.lower() + "!"\n',
         'def shout(s):\n    return s.upper() + "!"\n',
         ['assert shout("hi") == "HI!"']),
        ("max3", "def biggest(a, b, c):\n    return max(a, b)\n",
         "def biggest(a, b, c):\n    return max(a, b, c)\n",
         ["assert biggest(1, 9, 40) == 40"]),
        ("half4", "def half(x):\n    return x / 4\n",
         "def half(x):\n    return x / 2\n",
         ["assert half(9) == 4.5"]),
        ("absent", "def dist(a, b):\n    return a - b\n",
         "def dist(a, b):\n    return abs(a - b)\n",
         ["assert dist(3, 9) == 6", "assert dist(9, 3) == 6"]),
        ("identity", "def dup(s):\n    return s\n",
         "def dup(s):\n    return s * 2\n",
         ['assert dup("ab") == "abab"']),
        ("threshold", "def is_adult(age):\n    return age > 21\n",
         "def is_adult(age):\n    return age >= 18\n",
         ["assert is_adult(18) is True", "assert is_adult(17) is False"]),
        ("index", "def head(xs):\n    return xs[1]\n",
         "def head(xs):\n    return xs[0]\n",
         ["assert head([7, 8, 9]) == 7"]),
        ("first_only", "def total_list(xs):\n    return xs[0]\n",
         "def total_list(xs):\n    return sum(xs)\n",
         ["assert total_list([1, 2, 3]) == 6"]),
        ("no_rev", "def rev(s):\n    return s\n",
         "def rev(s):\n    return s[::-1]\n",
         ['assert rev("abc") == "cba"']),
        ("wrong_key", 'def count_a(s):\n    return s.count("b")\n',
         'def count_a(s):\n    return s.count("a")\n',
         ['assert count_a("banana") == 3']),
        ("clamp_low", "def clamp01(x):\n    return max(0, x)\n",
         "def clamp01(x):\n    return max(0, min(1, x))\n",
         ["assert clamp01(5) == 1", "assert clamp01(-5) == 0"]),
    ]
    out: list[Task] = []
    for i, (name, buggy, fixed, asserts) in enumerate(variants, start=1):
        tid = f"fix-{i:02d}"
        fn = _calc_fn_name(name, buggy)
        test_body = "\n".join(f"    {a}" for a in asserts)
        verifier = (f"from calc import {fn}\n\n\ndef test_{fn}() -> None:\n"
                    f"{test_body}\n")
        out.append(Task(
            id=tid, category="fix",
            goal=(f"[{tid}] أصلح العيب في calc.py ({name}) بحيث يمر ملف "
                  f"test_task.py دون تعديل الاختبار: استبدل التعريف المعيب "
                  f"بالكامل بتعريف صحيح."),
            seed={"calc.py": buggy, "test_task.py": verifier},
            expect=("calc.py",),
            solution_steps=({
                "file": "calc.py", "action": "edit", "risk": LOW,
                "reason": f"إصلاح عيب {name} في calc.py ليمر اختبار التحقق",
                "patch_hint": fixed,
                "find": buggy,  # ض6 (v1.58.0): استبدال فريد لا إلحاق
            },),
        ))
    return tuple(out)


def _test_tasks() -> tuple[Task, ...]:
    """12 tasks: a correct module exists; the plan must CREATE its tests."""
    variants: list[tuple[str, str, list[str]]] = [
        ("nummod", "def twice(x):\n    return x * 2\n",
         ["assert twice(4) == 8", "assert twice(0) == 0"]),
        ("strmod", "def shout(s):\n    return s.upper()\n",
         ['assert shout("hi") == "HI"']),
        ("listmod", "def first(xs):\n    return xs[0]\n",
         ["assert first([5, 6]) == 5"]),
        ("boolmod", "def neg(b):\n    return not b\n",
         ["assert neg(True) is False", "assert neg(False) is True"]),
        ("mathmod", "def average(xs):\n    return sum(xs) / len(xs)\n",
         ["assert average([2, 4, 6]) == 4.0"]),
        ("textmod", "def repeat(s, n):\n    return s * n\n",
         ['assert repeat("ab", 3) == "ababab"']),
        ("sortmod", "def top(xs):\n    return sorted(xs)[-1]\n",
         ["assert top([3, 1, 2]) == 3"]),
        ("unitmod", "def km_to_m(km):\n    return km * 1000\n",
         ["assert km_to_m(2) == 2000"]),
        ("signmod", "def sign(x):\n    return (x > 0) - (x < 0)\n",
         ["assert sign(-9) == -1", "assert sign(9) == 1",
          "assert sign(0) == 0"]),
        ("pairmod", "def swap(pair):\n    a, b = pair\n    return (b, a)\n",
         ["assert swap((1, 2)) == (2, 1)"]),
        ("censormod", 'def mask(s):\n    return s[0] + "*" * (len(s) - 1)\n',
         ['assert mask("abc") == "a**"']),
        ("ratemod", "def per_hour(total, hours):\n    return total / hours\n",
         ["assert per_hour(100, 4) == 25.0"]),
    ]
    out: list[Task] = []
    for i, (mod, code, asserts) in enumerate(variants, start=1):
        tid = f"test-{i:02d}"
        test_file = f"test_lib_{i:02d}.py"
        fn = code.split("def ")[1].split("(")[0].strip()
        out.append(Task(
            id=tid, category="test",
            goal=(f"[{tid}] الوحدة {mod}.py صحيحة لكنها بلا اختبارات؛ أنشئ "
                  f"ملف {test_file} باختبارات pytest للدالة {fn} بحيث تنجح، "
                  f"ثم شغّلها عبر tests_to_run."),
            seed={f"{mod}.py": code},
            expect=(test_file,),
            tests_to_run=(test_file,),
            solution_steps=({
                "file": test_file, "action": "create", "risk": LOW,
                "reason": f"الوحدة {mod} بلا تغطية — الاختبار مطلوب",
                "patch_hint": _create_test(mod, fn, asserts),
            },),
        ))
    return tuple(out)


def _docs_tasks() -> tuple[Task, ...]:
    """10 tasks: README is incomplete; each verifier demands one section."""
    keywords = ("التثبيت", "الاستخدام", "الأمثلة", "الترخيص", "المساهمة",
                "الاختبارات", "النشر", "الأسئلة الشائعة", "استكشاف الأخطاء",
                "خارطة الطريق")
    out: list[Task] = []
    for i, kw in enumerate(keywords, start=1):
        tid = f"docs-{i:02d}"
        closing = "مشروع قصير بلا توثيق كافٍ بعد.\n"
        out.append(Task(
            id=tid, category="docs",
            goal=(f"[{tid}] أكمل README.md بإضافة قسم عنوانه {kw} (عنوان من "
                  f"المستوى الثاني) بحيث يمر test_task.py دون تعديله."),
            seed={
                "README.md": f"# مشروع {i:02d}\n\n{closing}",
                "test_task.py": _docs_test(kw),
            },
            expect=("README.md",),
            solution_steps=({
                "file": "README.md", "action": "edit", "risk": LOW,
                "reason": f"قسم {kw} مطلوب ليمر اختبار التحقق",
                # ض6 (v1.58.0): استبدال السطر الختامي فريدًا بإضافة القسم بعده
                "find": closing,
                "patch_hint": closing + f"\n## {kw}\n\nقسم {kw}: شرح موجز ومثال تطبيقي.\n",
            },),
        ))
    return tuple(out)


_CACHE: dict[str, tuple[Task, ...]] | None = None


def _all() -> tuple[Task, ...]:
    global _CACHE
    if _CACHE is None:
        _CACHE = {
            "create": _create_tasks(), "fix": _fix_tasks(),
            "test": _test_tasks(), "docs": _docs_tasks(),
        }
    return tuple(t for cat in CATEGORIES for t in _CACHE[cat])


def catalog() -> tuple[Task, ...]:
    """All 50 tasks in stable order (create, fix, test, docs)."""
    return _all()


def by_category(category: str) -> tuple[Task, ...]:
    """Tasks of one category — raises ValueError for an unknown category."""
    if category not in CATEGORIES:
        raise ValueError(f"unknown category: {category!r}")
    if _CACHE is None:
        catalog()
    assert _CACHE is not None  # for type checkers; catalog() populated it
    return _CACHE[category]


def get_task(task_id: str) -> Task | None:
    """Lookup by id; None when absent (CLI uses this to validate input)."""
    return next((t for t in _all() if t.id == task_id), None)


def plan_for(task: Task) -> dict:
    """Reference solution as a RepairPlan-compatible JSON dict."""
    return {
        "goal": task.goal,
        "defects": [],
        "steps": [dict(s) for s in task.solution_steps],
        "tests_to_run": list(task.tests_to_run),
        "rollback": "استعادة مجلد العمل من البذور الأصلية للمهمة",
    }
