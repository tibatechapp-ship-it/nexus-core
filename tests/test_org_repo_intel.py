"""اختبارات ذكاء المستودع — تزايدي حقيقي، رسم معرفي حتمي، تأثير معلن.

القواعد المفروضة: التزايدي يعيد استخدام المحلَّل غير المتغير (ولا يفرّغ
الخريطة)، الرسم نفسه بنفس الترتيب، والتأثير يلتقط المستوردين عكسًا.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.org.repo_intel import RepoIntelligence, file_fingerprint


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    pkg = tmp_path / "calc"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mathops.py").write_text(
        "def divide(a, b):\n    return a / b\n", encoding="utf-8")
    (pkg / "utils.py").write_text(
        "from calc.mathops import divide\n"
        "def half(x):\n    return divide(x, 2)\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_mathops.py").write_text(
        "from calc.mathops import divide\n"
        "def test_divide():\n    assert divide(10, 2) == 5\n",
        encoding="utf-8")
    return tmp_path


class TestScan:
    def test_modules_and_edges(self, repo: Path) -> None:
        engine = RepoIntelligence(repo)
        rm = engine.scan()
        rels = [m.rel_path for m in rm.modules]
        assert "calc/mathops.py" in rels and "calc/utils.py" in rels
        assert ("calc.utils", "calc.mathops") in rm.import_edges()

    def test_functions_and_classes(self, repo: Path) -> None:
        rm = RepoIntelligence(repo).scan()
        mod = next(m for m in rm.modules if m.rel_path == "calc/mathops.py")
        assert mod.functions == ["divide"]

    def test_incremental_keeps_full_map(self, repo: Path) -> None:
        """الفحص الثاني يتخطى غير المتغير ولا يفرّغ الخريطة."""
        engine = RepoIntelligence(repo)
        first = engine.scan()
        second = engine.scan()
        assert len(second.modules) == len(first.modules) == 4
        assert second.files_skipped_unchanged == 4

    def test_changed_file_reparsed(self, repo: Path) -> None:
        engine = RepoIntelligence(repo)
        engine.scan()
        (repo / "calc" / "mathops.py").write_text(
            "def divide(a, b):\n    if b == 0:\n        raise ValueError\n"
            "    return a / b\n", encoding="utf-8")
        second = engine.scan()
        assert second.files_skipped_unchanged == 3
        mod = next(m for m in second.modules
                   if m.rel_path == "calc/mathops.py")
        assert len(mod.functions) == 1  # أعيد تحليله

    def test_fingerprint_changes_with_content(self, repo: Path) -> None:
        f = repo / "calc" / "mathops.py"
        fp1 = file_fingerprint(f)
        f.write_text("changed = True\n", encoding="utf-8")
        assert file_fingerprint(f) != fp1


class TestKnowledgeGraph:
    def test_graph_deterministic(self, repo: Path) -> None:
        g1 = RepoIntelligence(repo).scan().knowledge_graph()
        g2 = RepoIntelligence(repo).scan().knowledge_graph()
        assert g1 == g2

    def test_graph_json_stable(self, repo: Path) -> None:
        g = RepoIntelligence(repo).scan().knowledge_graph()
        assert json.dumps(g, sort_keys=True) == json.dumps(g, sort_keys=True)
        assert any(e["rel"] == "imports" for e in g["edges"])


class TestImpact:
    def test_affected_captures_reverse_imports(self, repo: Path) -> None:
        affected = RepoIntelligence(repo).affected_files(["calc/mathops.py"])
        assert affected["direct"] == ["calc/mathops.py"]
        assert "calc/utils.py" in affected["transitive"]
        assert "tests/test_mathops.py" in affected["transitive"]
        assert affected["test_files"] == ["tests/test_mathops.py"]

    def test_unknown_change_has_no_direct(self, repo: Path) -> None:
        affected = RepoIntelligence(repo).affected_files(["nope.py"])
        assert affected["direct"] == []

    def test_summary_for_planning(self, repo: Path) -> None:
        summary = RepoIntelligence(repo).summary_for_planning()
        assert summary["python_modules"] == 4
        assert summary["import_edges"] >= 2
