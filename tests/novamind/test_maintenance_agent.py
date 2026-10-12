"""
اختبار تكامل: Maintenance Agent + ProjectDoctor
"""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import tempfile
import shutil

# استيراد الوكيل والأداة
from novamind.agents.maintenance_agent import maintenance_agent
from novamind.tools.project_doctor import ProjectDoctor, DoctorReport, DiagnosisResult


@pytest.fixture
def temp_project():
    """ينشئ مشروعاً وهمياً مؤقتاً للاختبار."""
    tmp_dir = Path(tempfile.mkdtemp())
    
    (tmp_dir / "nova").mkdir()
    (tmp_dir / "nova" / "__init__.py").touch()
    (tmp_dir / "nova" / "core").mkdir()
    (tmp_dir / "nova" / "core" / "__init__.py").touch()
    
    (tmp_dir / "tests").mkdir()
    (tmp_dir / "tests" / "test_sample.py").touch()
    
    pyproject_content = """
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "nova-test"
version = "0.1.0"
"""
    (tmp_dir / "pyproject.toml").write_text(pyproject_content)
    
    yield tmp_dir
    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_maintenance_agent_health_check(temp_project):
    ctx = {"root_path": str(temp_project), "auto_fix": False}
    result = maintenance_agent.check_health(task="health_check", ctx=ctx)
    
    assert result is not None
    assert "ok" in result
    assert "summary_report" in result
    assert "details" in result
    print(f"\n📋 Health Check Report:\n{result['summary_report']}")


def test_maintenance_agent_with_auto_fix(temp_project):
    workflows_dir = temp_project / ".github" / "workflows"
    workflows_dir.mkdir(parents=True)
    
    ci_content = """
name: CI
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run tests
        run: pytest tests/
"""
    (workflows_dir / "tests.yml").write_text(ci_content)
    
    ctx = {"root_path": str(temp_project), "auto_fix": True}
    result = maintenance_agent.check_health(task="auto_fix_check", ctx=ctx)
    
    assert result["fixes_applied"] > 0, "Expected at least one fix to be applied."
    patched_content = (workflows_dir / "tests.yml").read_text()
    assert "pip install -e ." in patched_content, "CI file was not patched correctly."
    print("\n✅ CI file patched successfully.")


def test_project_doctor_dry_run_safety(temp_project):
    workflows_dir = temp_project / ".github" / "workflows"
    workflows_dir.mkdir(parents=True)
    ci_content = "name: CI\non: [push]\n"
    ci_file = workflows_dir / "tests.yml"
    ci_file.write_text(ci_content)
    original_content = ci_file.read_text()
    
    doctor = ProjectDoctor(root=str(temp_project), dry_run=True)
    report = doctor.diagnose_and_heal()
    
    assert ci_file.read_text() == original_content, "Dry run modified the file!"
    print("\n🛡️ Dry run safety verified: No files were modified.")


def test_project_doctor_creates_pyproject_if_missing():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        doctor = ProjectDoctor(root=str(tmp_path), dry_run=False)
        report = doctor.diagnose_and_heal()
        
        critical_issues = [i for i in report.issues_found if i.severity == "CRITICAL"]
        assert len(critical_issues) > 0
        assert (tmp_path / "pyproject.toml").exists(), "pyproject.toml was not created."
        print("\n📦 pyproject.toml created successfully.")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
