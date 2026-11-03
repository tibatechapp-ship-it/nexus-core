"""Analyzer tests (M2.1) — AST module map on a synthetic tree."""

from __future__ import annotations

from pathlib import Path

from src.coder.analyzer import analyze_repo


def _make_tree(tmp_path: Path) -> Path:
    (tmp_path / "pkg").mkdir(parents=True)
    (tmp_path / "pkg" / "__init__.py").write_text('"""Pkg first line.\nMore."""\n')
    (tmp_path / "pkg" / "mod.py").write_text(
        '"""Mod doc line."""\nimport os\nimport json\nimport os\n'
        "from pathlib import Path\n\n\ndef f() -> int:\n    return 1\n"
    )
    (tmp_path / "broken.py").write_text("def (:\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "junk.py").write_text("x = 1\n")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "secret.py").write_text("x = 2\n")
    (tmp_path / "novamind").mkdir()
    (tmp_path / "novamind" / "opt.py").write_text("x = 3\n")
    return tmp_path


def test_analyze_maps_all_visible_modules(tmp_path: Path) -> None:
    result = analyze_repo(_make_tree(tmp_path))
    names = {m["name"] for m in result["modules"]}
    assert {"pkg", "pkg.mod", "broken"} <= names
    assert not any("secret" in m["name"] or "opt" in m["name"] or "junk" in m["name"]
                   for m in result["modules"])


def test_analyze_docstring_first_line(tmp_path: Path) -> None:
    result = analyze_repo(_make_tree(tmp_path))
    docs = {m["name"]: m["doc"] for m in result["modules"]}
    assert docs["pkg.mod"] == "Mod doc line."
    assert docs["pkg"] == "Pkg first line."


def test_analyze_imports_deduped_and_sorted(tmp_path: Path) -> None:
    result = analyze_repo(_make_tree(tmp_path))
    mod = next(m for m in result["modules"] if m["name"] == "pkg.mod")
    assert mod["imports"] == ["json", "os", "pathlib"]


def test_analyze_flags_syntax_error_module(tmp_path: Path) -> None:
    result = analyze_repo(_make_tree(tmp_path))
    broken = next(m for m in result["modules"] if m["name"] == "broken")
    assert broken.get("syntax_error") is True
    assert broken["path"] == "broken.py"


def test_analyze_counts_loc_and_summary(tmp_path: Path) -> None:
    result = analyze_repo(_make_tree(tmp_path))
    assert result["total_loc"] == sum(m["loc"] for m in result["modules"])
    assert result["summary"].endswith("LOC")
    assert result["summary"].startswith("3 modules")


def test_analyze_external_imports(tmp_path: Path) -> None:
    result = analyze_repo(_make_tree(tmp_path))
    assert "os" in result["external_imports"]
    assert "pathlib" in result["external_imports"]


def test_analyze_empty_repo(tmp_path: Path) -> None:
    result = analyze_repo(tmp_path)
    assert result["modules"] == []
    assert result["total_loc"] == 0
    assert result["external_imports"] == []


def test_analyze_module_name_strips_init(tmp_path: Path) -> None:
    result = analyze_repo(_make_tree(tmp_path))
    pkg = next(m for m in result["modules"] if m["path"] == "pkg/__init__.py")
    assert pkg["name"] == "pkg"
