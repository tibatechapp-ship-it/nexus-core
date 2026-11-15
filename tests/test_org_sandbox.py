"""اختبارات العزل التنفيذي ونسخ العمل — حدود، مسارات مقيّدة، دليل كامل.

القواعد المفروضة: كل تنفيذ داخل حدود الموارد والمهلة، البيئة مُنقّحة
بلا توكنات، والكتابة لا تخرج عن جذر نسخة العمل، والأصل لا يُلمس.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.org.sandbox import (
    RunResult,
    SandboxLimits,
    WorkspaceRunner,
    Worktree,
    runner_from_ops_policy,
)


@pytest.fixture()
def runner() -> WorkspaceRunner:
    return WorkspaceRunner(SandboxLimits(timeout_s=20, mem_mb=256, cpu_s=20))


class TestRunner:
    def test_simple_run(self, runner: WorkspaceRunner) -> None:
        result = runner.run(["python3", "-c", "print('hey')"], Path("."))
        assert result.returncode == 0 and "hey" in result.stdout

    def test_run_python_probe(self, runner: WorkspaceRunner) -> None:
        result = runner.run_python("print(40 + 2)")
        assert result.returncode == 0 and "42" in result.stdout

    def test_timeout_produces_evidence(self) -> None:
        tight = WorkspaceRunner(SandboxLimits(timeout_s=1, mem_mb=256,
                                              cpu_s=20))
        result = tight.run_python("import time; time.sleep(5)")
        assert result.timed_out is True
        detail = result.to_detail()
        assert detail["timed_out"] is True

    def test_summary_deterministic_shape(self, runner: WorkspaceRunner) -> None:
        result = runner.run_python("print('x')")
        assert "python3" in result.summary()

    def test_env_sanitized(self, runner: WorkspaceRunner) -> None:
        """بيئة العملية الابن بلا توكنات موروثة."""
        import os
        os.environ["ORG_TEST_SECRET_TOKEN"] = "s3cr3t"
        result = runner.run_python(
            "import os; print('ORG_TEST_SECRET_TOKEN' in os.environ)")
        assert result.returncode == 0
        assert "False" in result.stdout

    def test_memory_limit_enforced(self) -> None:
        tight = WorkspaceRunner(SandboxLimits(timeout_s=20, mem_mb=64,
                                              cpu_s=20))
        result = tight.run_python("x = 'a' * (200 * 1024 * 1024)")
        assert result.returncode != 0


class TestWorktree:
    def test_from_source_copies_files(self, tmp_path: Path) -> None:
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "m.py").write_text("x = 1\n", encoding="utf-8")
        wt = Worktree.from_source(tmp_path, files=["pkg/m.py"])
        try:
            assert wt.read("pkg/m.py") == "x = 1\n"
        finally:
            wt.cleanup()

    def test_write_and_path_escape_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("1\n", encoding="utf-8")
        wt = Worktree.from_source(tmp_path, files=["a.py"])
        try:
            wt.write("sub/new.py", "x = 2\n")
            assert wt.read("sub/new.py") == "x = 2\n"
            with pytest.raises(ValueError, match="خارج"):
                wt.write("../escape.py", "bad")
        finally:
            wt.cleanup()

    def test_original_untouched(self, tmp_path: Path) -> None:
        original = tmp_path / "m.py"
        original.write_text("original\n", encoding="utf-8")
        wt = Worktree.from_source(tmp_path, files=["m.py"])
        try:
            wt.write("m.py", "changed\n")
            assert original.read_text(encoding="utf-8") == "original\n"
        finally:
            wt.cleanup()

    def test_apply_changes(self, tmp_path: Path) -> None:
        (tmp_path / "m.py").write_text("old\n", encoding="utf-8")
        wt = Worktree.from_source(tmp_path, files=["m.py"])
        try:
            applied = wt.apply_changes([
                {"path": "m.py", "content": "new\n"},
                {"path": "extra.py", "content": "e = 1\n"},
            ])
            # ترتيب التطبيق يتبع ترتيب الإدخال لا الفرز
            assert applied == ["m.py", "extra.py"]
        finally:
            wt.cleanup()

    def test_whole_copy_skips_pycache(self, tmp_path: Path) -> None:
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "junk.pyc").write_bytes(b"junk")
        (tmp_path / "main.py").write_text("print('ok')\n", encoding="utf-8")
        wt = Worktree.from_source(tmp_path, whole=True)
        try:
            assert (wt.root / "main.py").exists()
            assert not (wt.root / "__pycache__").exists()
        finally:
            wt.cleanup()


class TestOpsPolicyAdapter:
    def test_runner_from_ops_policy(self) -> None:
        """دمج الموجتين: سياسة العزل التشغيلية تُقرأ لا تُخترع."""

        class FakePolicy:
            cpu_seconds = 7
            memory_bytes = 256 * 1024 * 1024
            timeout_sec = 45
            network = "none"
            container_runner = None

        runner = runner_from_ops_policy(FakePolicy())
        assert runner.limits.timeout_s == 45
        assert runner.limits.mem_mb == 256
        assert runner.limits.cpu_s == 7
        assert runner.limits.network is False
        assert runner.limits.container_runner == ""

    def test_container_runner_hook_detected(self) -> None:
        class PolicyWithContainer:
            cpu_seconds = 5
            memory_bytes = 512 * 1024 * 1024
            timeout_sec = 30
            network = "none"

            @staticmethod
            def container_runner(code: str, name: str) -> dict:
                return {}

        runner = runner_from_ops_policy(PolicyWithContainer())
        assert runner.limits.container_runner == "container"


class TestRunResultEvidence:
    def test_to_detail_shape(self, runner: WorkspaceRunner) -> None:
        result: RunResult = runner.run_python("print('ok')")
        detail = result.to_detail()
        for key in ("command", "returncode", "timed_out", "duration_ms",
                    "isolation", "stdout", "stderr"):
            assert key in detail
