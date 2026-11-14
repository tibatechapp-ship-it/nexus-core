"""اختبارات فهرس الذكاء — بناء واستعلام وبُهتان.

العقد المفحوص: فهرس حتمي من ast وحده، استعلامات دقيقة (تعريفات/مراجع/
شريحة)، كشف البُهتان بمجرد تغير ملف واحد، وتالف يُعلن لا يُصطنع.
"""

from __future__ import annotations

import json

import pytest

from src.orchestrator.code_index import (
    IGNORED_DIRS, INDEX_VERSION, CodeIndex, build_index, iter_python_files,
)


@pytest.fixture()
def sample_repo(tmp_path):
    """مستودع عينة: وحدتان ترتبطان + ملف مهمل لا يدخل الفهرس."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "core.py").write_text(
        'import os\n'
        'from pkg.helper import inflate\n'
        '\n'
        'class Engine:\n'
        '    """محرك العينة."""\n'
        '    def start(self):\n'
        '        return inflate(1)\n'
        '\n'
        'def run(x, *args, **kwargs):\n'
        '    return x\n',
        encoding="utf-8")
    (tmp_path / "pkg" / "helper.py").write_text(
        'def inflate(value):\n'
        '    return value * 2\n',
        encoding="utf-8")
    (tmp_path / "pkg" / "__pycache__").mkdir()
    (tmp_path / "pkg" / "__pycache__" / "junk.py").write_text("X = 1\n", encoding="utf-8")
    return tmp_path


# ── البناء ───────────────────────────────────────────────────────────

def test_build_index_is_deterministic(sample_repo):
    a = build_index(sample_repo)
    b = build_index(sample_repo)
    assert a["files"] == b["files"]
    assert a["errors"] == b["errors"]


def test_build_index_ignores_pycache(sample_repo):
    idx = CodeIndex(build_index(sample_repo))
    assert all("__pycache__" not in f for f in idx._files)
    assert "__pycache__" in IGNORED_DIRS


def test_build_index_records_symbols(sample_repo):
    idx = CodeIndex(build_index(sample_repo))
    core = idx._files["pkg/core.py"]
    assert {c["name"] for c in core["classes"]} == {"Engine"}
    assert "run" in {f["name"] for f in core["functions"]}
    assert "pkg.helper" in core["imports"]


def test_broken_file_is_declared_not_fatal(sample_repo):
    (sample_repo / "pkg" / "broken.py").write_text("def (:\n", encoding="utf-8")
    idx = CodeIndex(build_index(sample_repo))
    assert idx.errors and "broken.py" in idx.errors[0]
    assert idx.file_count >= 2  # الباقي فُهرس رغم التالف


def test_iter_python_files_sorted(sample_repo):
    files = [p.name for p in iter_python_files(sample_repo)]
    assert files == sorted(files)


# ── الدورة الكاملة ───────────────────────────────────────────────────

def test_save_and_load_roundtrip(sample_repo, tmp_path):
    idx = CodeIndex(build_index(sample_repo))
    path = idx.save(tmp_path / "memory" / "code_index.json")
    loaded = CodeIndex.load(path)
    assert loaded._data == idx._data
    assert loaded.lookup("inflate")[0].file == "pkg/helper.py"


def test_load_rejects_broken_file(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="تحميل"):
        CodeIndex.load(path)


def test_load_rejects_wrong_version(tmp_path):
    path = tmp_path / "old.json"
    path.write_text(json.dumps({"version": INDEX_VERSION + 99, "files": {}}),
                    encoding="utf-8")
    with pytest.raises(ValueError, match="نسخة"):
        CodeIndex.load(path)


def test_load_rejects_missing_files_field(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="files"):
        CodeIndex.load(path)


# ── البُهتان ─────────────────────────────────────────────────────────

def test_fresh_index_not_stale(sample_repo):
    idx = CodeIndex.build(sample_repo)
    assert not idx.is_stale(sample_repo)


def test_touching_file_makes_index_stale(sample_repo):
    import os
    import time
    idx = CodeIndex.build(sample_repo)
    target = sample_repo / "pkg" / "helper.py"
    os.utime(target, (time.time() + 5, time.time() + 5))
    assert idx.is_stale(sample_repo)


def test_new_file_makes_index_stale(sample_repo):
    idx = CodeIndex.build(sample_repo)
    (sample_repo / "pkg" / "newborn.py").write_text("X = 1\n", encoding="utf-8")
    assert idx.is_stale(sample_repo)


def test_deleted_file_makes_index_stale(sample_repo):
    idx = CodeIndex.build(sample_repo)
    (sample_repo / "pkg" / "helper.py").unlink()
    assert idx.is_stale(sample_repo)


# ── الاستعلام ────────────────────────────────────────────────────────

def test_lookup_finds_class_and_function(sample_repo):
    idx = CodeIndex.build(sample_repo)
    engine_defs = idx.lookup("Engine")
    assert engine_defs and engine_defs[0].kind == "class"
    assert engine_defs[0].line == 4
    inflate = idx.lookup("inflate")
    assert inflate and inflate[0].kind == "function"
    assert "inflate(value)" in inflate[0].signature


def test_lookup_rejects_invalid_identifiers(sample_repo):
    idx = CodeIndex.build(sample_repo)
    assert idx.lookup("") == []
    assert idx.lookup("not a name!") == []


def test_refs_lists_importers_and_definers(sample_repo):
    idx = CodeIndex.build(sample_repo)
    refs = idx.refs("inflate")
    assert "pkg/helper.py" in refs        # المُعرِّف
    assert "pkg/core.py" in refs          # المستورد
    assert refs == sorted(refs)


def test_slice_is_compact_and_declarative(sample_repo):
    idx = CodeIndex.build(sample_repo)
    text = idx.slice_for("inflate")
    assert "شريحة inflate" in text
    assert "pkg/helper.py" in text
    assert "pkg/core.py" in text


def test_slice_for_unknown_name_declares_truth(sample_repo):
    idx = CodeIndex.build(sample_repo)
    assert "لا أثر" in idx.slice_for("no_such_symbol_anywhere")


def test_slice_rejects_invalid_name(sample_repo):
    idx = CodeIndex.build(sample_repo)
    assert "غير صالح" in idx.slice_for("bad name")


def test_slice_caps_long_lists(sample_repo):
    idx = CodeIndex.build(sample_repo)
    text = idx.slice_for("inflate", max_defs=0, max_refs=0)
    assert "مقصوصاً" in text
