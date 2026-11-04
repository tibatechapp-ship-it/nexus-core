"""اختبارات دخانية للأمثلة الخمسة — بوابة خروج م5-ب.

كل مثال يُشغَّل كعملية منفصلة (كما يفعل المستخدم تمامًا) ويجب أن
يخرج 0 مع علامات مخرجات معلنة — بلا مفاتيح وبلا إنترنت.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: (ملف المثال، علامات يجب ظهورها في المخرجات)
EXAMPLES: list[tuple[str, tuple[str, ...]]] = [
    ("01_first_council.py", ("الحكم", "الدرجة")),
    ("02_agent_run.py", ("الأسطول:", "نجاح: True")),
    ("03_durable_flow.py", ("fail-closed", "publish ✓")),
    ("04_trace_replay.py", ("خطوات مسجّلة", "الخصوصية")),
    ("05_a2a_roundtrip.py", ("صالحة: True", "PrivacyError")),
]


@pytest.mark.parametrize(("script", "markers"), EXAMPLES,
                         ids=[e[0] for e in EXAMPLES])
def test_example_smoke(script: str, markers: tuple[str, ...]) -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "examples" / script)],
        capture_output=True, text=True, timeout=180,
        cwd=str(ROOT), env={"PATH": "/usr/bin:/bin", "HOME": "/home/z"},
    )
    assert proc.returncode == 0, f"{script} فشل:\n{proc.stdout}\n{proc.stderr}"
    for marker in markers:
        assert marker in proc.stdout, f"{script}: علامة مفقودة «{marker}»"


def test_examples_dir_has_five_scripts() -> None:
    scripts = sorted(p.name for p in (ROOT / "examples").glob("*.py"))
    assert len(scripts) == 5
