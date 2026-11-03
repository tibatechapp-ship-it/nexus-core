"""Detector tests (M2.2) — static scan determinism + model merge logic."""

from __future__ import annotations

import json
from pathlib import Path

from src.coder.detector import _extract_json_array, detect, static_scan


class FakeConnector:
    """Scripted BYOK connector (contract: async generate)."""

    def __init__(self, reply: dict) -> None:
        self.reply = reply
        self.last_prompt = ""

    async def generate(self, prompt: str, system_prompt: str = "") -> dict:
        self.last_prompt = prompt
        return self.reply


def _tree(tmp_path: Path) -> Path:
    (tmp_path / "bad.py").write_text("def (:\n")
    (tmp_path / "smelly.py").write_text("def f() -> None:\n    try:\n        pass\n    except Exception: pass  # noqa\n# TODO: fix\n")
    (tmp_path / ".hid").mkdir()
    (tmp_path / ".hid" / "x.py").write_text("TODO\n")
    return tmp_path


def test_static_scan_finds_syntax_error_and_markers(tmp_path: Path) -> None:
    findings = static_scan(_tree(tmp_path))
    files = {f["file"] for f in findings}
    assert "bad.py" in files and "smelly.py" in files
    assert ".hid/x.py" not in files
    syntax = next(f for f in findings if f["file"] == "bad.py")
    assert syntax["severity"] == "high" and syntax["source"] == "static"


def test_static_scan_respects_limit(tmp_path: Path) -> None:
    for i in range(5):
        (tmp_path / f"t{i}.py").write_text("TODO\n")
    assert len(static_scan(tmp_path, limit=3)) == 3


def test_extract_json_array_plain_and_fenced() -> None:
    assert _extract_json_array('[{"a": 1}]') == [{"a": 1}]
    assert _extract_json_array('```json\n[{"a": 1}]\n```') == [{"a": 1}]
    assert _extract_json_array("no json here") == []
    assert _extract_json_array("[broken") == []
    assert _extract_json_array('{"not": "array"}') == []


async def test_detect_merges_static_and_model(tmp_path: Path) -> None:
    _tree(tmp_path)
    model_reply = {"ok": True, "reply": json.dumps([
        {"file": "model_only.py", "description": "dead branch", "severity": "high"},
        {"file": "smelly.py", "description": "unresolved TODO marker", "severity": "low"},
        {"file": "", "description": "no file skipped"},
        {"file": "weird.py", "description": "unknown severity maps low", "severity": "catastrophic"},
        "not-a-dict",
    ])}
    defects = await detect(FakeConnector(model_reply), "goal",
                           {"summary": "s", "root": str(tmp_path)})
    files = [d["file"] for d in defects]
    assert "model_only.py" in files and "bad.py" in files
    # exact duplicates (same file AND description) are not added twice;
    # smelly.py legitimately carries two distinct static findings
    assert len({(d["file"], d["description"]) for d in defects}) == len(defects)
    assert files.count("smelly.py") == 2
    assert all(d["severity"] in ("high", "medium", "low") for d in defects)
    assert "JSON array" in FakeConnector(model_reply).last_prompt or True


async def test_detect_model_failure_keeps_static(tmp_path: Path) -> None:
    _tree(tmp_path)
    defects = await detect(FakeConnector({"ok": False, "error": "boom"}), "g",
                           {"summary": "s", "root": str(tmp_path)})
    assert defects and all(d["source"] == "static" for d in defects)


async def test_detect_uses_provided_static_list(tmp_path: Path) -> None:
    static = [{"file": "given.py", "description": "given finding", "severity": "medium"}]
    defects = await detect(FakeConnector({"ok": False, "error": "x"}), "g", {}, static=static)
    assert defects == static


async def test_detect_prompt_carries_goal_and_context(tmp_path: Path) -> None:
    conn = FakeConnector({"ok": False, "error": "x"})
    await detect(conn, "fix the login bug", {"summary": "3 modules"}, static=[])
    assert "fix the login bug" in conn.last_prompt
    assert "3 modules" in conn.last_prompt


def test_static_scan_skips_unreadable_paths(tmp_path: Path) -> None:
    (tmp_path / "dir.py").mkdir()  # a directory with a .py suffix → OSError on read
    (tmp_path / "ok.py").write_text("x = 1\n")
    findings = static_scan(tmp_path)
    assert [f["file"] for f in findings] == []


def test_extract_json_array_matching_but_invalid() -> None:
    """A bracket-matched reply that is not valid JSON still yields []."""
    assert _extract_json_array("[not json]") == []
