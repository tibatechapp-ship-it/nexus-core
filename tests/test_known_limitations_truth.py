"""ب2.4 — وثيقة القيود تقول الصدق: عدّ TODO يطابق الوثيقة حرفيًا.

الفجوة كانت: الوثيقة أعلنت 22 وتفاصيلها قديمة (سطور تحركت، بنود ناقصة).
الاختبار يمسح ``src/novamind/`` لكل ``TODO|FIXME`` ويطابق:

1. المجموع المعلن في الوثيقة == عدد التطابقات الفعلي.
2. كل تطابق فعلي (ملف:سطر) معلن في جدول الوثيقة — لا كسر صامت جديد.
3. جدول الربطين المعماريين يحمل قرارَي ب2.2/ب2.3 (لا تأجيل بعد اليوم).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIR = ROOT / "src" / "novamind"
DOC = ROOT / "docs" / "known-limitations.md"

_MARKER = re.compile(r"TODO|FIXME")


def _actual_markers() -> list[tuple[str, int]]:
    """كل تطابق TODO/FIXME في src/novamind بصيغة (مسار نسبي، سطر)."""
    found: list[tuple[str, int]] = []
    for path in sorted(SCAN_DIR.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        with open(path, encoding="utf-8", errors="replace") as f:
            for lineno, line in enumerate(f, start=1):
                if _MARKER.search(line):
                    found.append((rel, lineno))
    return found


def _declared_markers() -> set[tuple[str, int]]:
    """البنود المعلنة في الوثيقة بصيغة (ملف، سطر)."""
    declared: set[tuple[str, int]] = set()
    for line in DOC.read_text(encoding="utf-8").splitlines():
        row = re.match(r"^\|\s*\d+\s*\|\s*`([^`]+)`\s*\|\s*(\d+)\s*\|", line)
        if row:
            declared.add((row.group(1), int(row.group(2))))
    return declared


def _declared_total() -> int | None:
    """المجموع المعلن في عنوان الوثيقة — ``19 total`` مثلًا."""
    head = re.search(r"## TODO/FIXME Markers — (\d+) total", DOC.read_text(encoding="utf-8"))
    return int(head.group(1)) if head else None


def test_document_total_matches_code_reality() -> None:
    actual = _actual_markers()
    declared_total = _declared_total()
    assert declared_total is not None, "عنوان الوثيقة بلا مجموع معلن"
    assert declared_total == len(actual), (
        f"الوثيقة تعلن {declared_total} والواقع {len(actual)} — جدّد "
        "docs/known-limitations.md في نفس الـPR"
    )


def test_every_todo_marker_is_declared_in_document() -> None:
    declared = _declared_markers()
    undeclared = [m for m in _actual_markers() if m not in declared]
    assert not undeclared, (
        f"TODO غير معلن في docs/known-limitations.md: {undeclared[:6]} — أعلنه بقراره أو أصلحه"
    )


def test_document_does_not_declare_ghosts() -> None:
    """لا بنود شبحية: كل بند معلن له تطابق فعلي (لا وثيقة متقادمة)."""
    actual = set(_actual_markers())
    ghosts = sorted(m for m in _declared_markers() if m not in actual)
    assert not ghosts, f"بنود معلنة بلا وجود في الكود: {ghosts[:6]} — احذفها من الوثيقة"


def test_architectural_links_are_resolved_not_deferred() -> None:
    """ب2.2/ب2.3: الربطان معماريان منفّذان في الوثيقة باختبارهما."""
    text = DOC.read_text(encoding="utf-8")
    assert "resolved in v1.49.1" in text
    assert "orchestrator → Queue Manager (ب2.2)" in text
    assert "executor → core/llm_router (ب2.3)" in text
    assert "Architectural decision needed" not in text, (
        "لا تأجيل معماري بعد اليوم — القرار أو التنفيذ معلنان"
    )
