"""نسخة مبسطة من ProjectDoctor للاختبار."""
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("nova.tools.project_doctor")

@dataclass
class DiagnosisResult:
    category: str
    severity: str
    message: str
    file_path: Optional[str] = None
    auto_fixable: bool = False

@dataclass
class DoctorReport:
    issues_found: List[DiagnosisResult] = field(default_factory=list)
    fixes_applied: List[str] = field(default_factory=list)
    skipped_fixes: List[str] = field(default_factory=list)
    
    def summary(self) -> str:
        return f"Issues: {len(self.issues_found)}, Fixes: {len(self.fixes_applied)}"


class ProjectDoctor:
    def __init__(self, root: str = ".", dry_run: bool = True):
        self.root = Path(root).resolve()
        self.dry_run = dry_run
        self.report = DoctorReport()
        
    def diagnose_and_heal(self):
        # فحص pyproject.toml
        if not (self.root / "pyproject.toml").exists():
            self.report.issues_found.append(DiagnosisResult(
                category="PACKAGING",
                severity="CRITICAL",
                message="Missing 'pyproject.toml'.",
                auto_fixable=True
            ))
            if not self.dry_run:
                (self.root / "pyproject.toml").write_text("[project]\nname='nova-test'\nversion='0.1.0'\n")
                self.report.fixes_applied.append("Created pyproject.toml")
            else:
                self.report.skipped_fixes.append("Would create pyproject.toml")
        
        # فحص CI
        ci_dir = self.root / ".github" / "workflows"
        if ci_dir.exists():
            for f in ci_dir.glob("*.yml"):
                content = f.read_text()
                if "pytest" in content and "pip install -e" not in content:
                    self.report.issues_found.append(DiagnosisResult(
                        category="CI_CONFIG",
                        severity="CRITICAL",
                        message=f"Missing install step in {f.name}",
                        file_path=str(f),
                        auto_fixable=True
                    ))
                    if not self.dry_run:
                        f.write_text(content.replace("pytest", "python -m pip install -e .\n      - run: pytest"))
                        self.report.fixes_applied.append(f"Patched {f.name}")
                    else:
                        self.report.skipped_fixes.append(f"Would patch {f.name}")
        
        return self.report
