"""بوابة م1 — الجذر نقطة إطلاق فقط (docs/V2_ROADMAP.md م1).

منذ v1.53.0 كل الكود الحي يسكن تحت ``src/``؛ الجذر يسمح بـ ``main.py``
وحده. كما تتحقق البوابة أن استثناءات حزمة ``src/legacy_root`` المجمدة
معلنة فعلاً في البوابات الثلاث (تغطية/أنماط/mypy) — استثناء غير معلن
يُسقط CI.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWED_ROOT_PY: frozenset[str] = frozenset({"main.py"})


def test_root_contains_only_the_launcher() -> None:
    """صفر ملفات .py حرة في الجذر عدا main.py."""
    found = {p.name for p in ROOT.glob("*.py")}
    drift = found - ALLOWED_ROOT_PY
    missing = ALLOWED_ROOT_PY - found
    assert not drift, f"ملفات جذرية جديدة غير مسموحة: {sorted(drift)}"
    assert not missing, f"نقطة الإطلاق مفقودة: {sorted(missing)}"


def test_frozen_legacy_root_package_exists_and_is_declared() -> None:
    """الحزمة المجمدة موجودة واستثناءاتها في البوابات الثلاث معلنة."""
    pkg = ROOT / "src" / "legacy_root"
    assert (pkg / "__init__.py").is_file()
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "src/legacy_root/*" in data["tool"]["coverage"]["run"]["omit"], (
        "استثناء تغطية src/legacy_root غير معلن"
    )
    assert "src/legacy_root" in data["tool"]["ruff"]["extend-exclude"], (
        "استثناء ruff لـ src/legacy_root غير معلن"
    )
    assert any("legacy_root" in e for e in data["tool"]["mypy"]["exclude"]), (
        "استثناء mypy لـ src/legacy_root غير معلن"
    )
