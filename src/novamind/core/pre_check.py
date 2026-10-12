"""
import os
Security Pre-Check — Final gate before delivering code to user.

Part of Proactive Agent Pipeline:
  Gatekeeper → Planner → Executor → [Pre-Check] → Output

Layers:
1. Block patterns (critical — cannot deliver)
2. Auto-fixes (apply automatically)
3. Warnings (notify user)
4. AST-based checks (Python)
"""
import re
import ast
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("core.pre_check")


class PreCheckDecision(str, Enum):
    CLEAN = "clean"
    AUTO_FIXED = "auto_fixed"
    WARN = "warn"
    BLOCK = "block"


@dataclass
class PreCheckIssue:
    severity: str
    category: str
    line: Optional[int]
    column: Optional[int]
    message: str
    snippet: str = ""
    auto_fixable: bool = False
    suggested_fix: str = ""

    def to_dict(self) -> Dict:
        return {
            "severity": self.severity,
            "category": self.category,
            "line": self.line,
            "message": self.message,
            "snippet": self.snippet[:200],
            "auto_fixable": self.auto_fixable,
            "suggested_fix": self.suggested_fix,
        }


@dataclass
class PreCheckResult:
    decision: str
    original_code: str
    final_code: str
    issues: List[PreCheckIssue] = field(default_factory=list)
    auto_fixes_applied: int = 0
    warnings_count: int = 0
    blocks_count: int = 0
    language: str = "python"

    def to_dict(self) -> Dict:
        return {
            "decision": self.decision,
            "issues_count": len(self.issues),
            "auto_fixes_applied": self.auto_fixes_applied,
            "warnings_count": self.warnings_count,
            "blocks_count": self.blocks_count,
            "issues": [i.to_dict() for i in self.issues],
            "language": self.language,
            "code_changed": self.original_code != self.final_code,
        }


# ═══════════════════════════════════════════════════════
# Auto-Fix Patterns
# ═══════════════════════════════════════════════════════
AUTO_FIXES = [
    {
        "pattern": r'\beval\s*\(\s*([^)]+)\s*\)',
        "replacement": r'safe_eval(\1)  # auto-blocked eval()',
        "category": "unsafe_eval",
        "severity": "high",
        "message": "eval() is dangerous — replaced with safe_eval placeholder",
    },
    {
        "pattern": r'\bexec\s*\(\s*([^)]+)\s*\)',
        "replacement": r'# exec() was blocked for security: \1',
        "category": "unsafe_exec",
        "severity": "high",
        "message": "exec() is dangerous — commented out",
    },
    {
        "pattern": r'(["\'])sk-[A-Za-z0-9]{20,}\1',
        "replacement": r'"YOUR_API_KEY_HERE"  # was hardcoded',
        "category": "hardcoded_secret",
        "severity": "critical",
        "message": "Hardcoded API key replaced with placeholder",
    },
    {
        "pattern": r'(["\'])AKIA[0-9A-Z]{16}\1',
        "replacement": r'"YOUR_AWS_KEY_HERE"  # was hardcoded',
        "category": "hardcoded_aws",
        "severity": "critical",
        "message": "Hardcoded AWS key replaced",
    },
    {
        "pattern": r'(\b(?:password|passwd|pwd|secret|token)\s*=\s*)(["\'])([^"\']{6,})\2',
        "replacement": r'\1os.environ.get("SECRET_VAR", "changeme")  # was hardcoded',
        "category": "hardcoded_password",
        "severity": "high",
        "message": "Hardcoded credential replaced with env var",
    },
]

WARNING_PATTERNS = [
    (r'\bshell\s*=\s*True\b', "shell_injection", "medium", "shell=True vulnerable to injection"),
    (r'\b__import__\s*\(', "dynamic_import", "medium", "Dynamic import may load untrusted modules"),
    (r'\byaml\.load\s*\([^)]*\)', "unsafe_yaml", "medium", "yaml.load() without SafeLoader"),
    (r'\brequests\.(get|post|put)\s*\([^)]*verify\s*=\s*False', "ssl_disabled", "medium", "SSL verification disabled"),
    (r'\bhashlib\.(md5|sha1)\b', "weak_crypto", "low", "Weak hash — use SHA-256+"),
]

BLOCK_PATTERNS = [
    (r'\bos\.system\s*\(\s*["\'].*\b(rm\s+-rf|format\s+[a-z]|del\s+/[fF])', "destructive_command", "critical", "Destructive system command"),
    (r'\b(sh|bash)\s+-c\s+["\'].*\brm\s+-rf\s+/', "shell_destructive", "critical", "Destructive shell command"),
    (r'\bsocket\b.*\b(bind|listen)\s*\(\s*["\']0\.0\.0\.0', "backdoor_listener", "critical", "Potential backdoor listener"),
]


class SecurityPreCheck:
    def __init__(self, auto_fix_enabled: bool = True):
        self.auto_fix_enabled = auto_fix_enabled
        self._compile()

    def _compile(self):
        self._auto_fixes = []
        for fix in AUTO_FIXES:
            try:
                self._auto_fixes.append({
                    "regex": re.compile(fix["pattern"], re.IGNORECASE | re.MULTILINE),
                    "replacement": fix["replacement"],
                    "category": fix["category"],
                    "severity": fix["severity"],
                    "message": fix["message"],
                })
            except re.error as e:
                logger.warning(f"bad fix: {e}")

        self._warnings = []
        for pattern, category, severity, message in WARNING_PATTERNS:
            try:
                self._warnings.append((re.compile(pattern, re.IGNORECASE), category, severity, message))
            except re.error:
                pass

        self._blocks = []
        for pattern, category, severity, message in BLOCK_PATTERNS:
            try:
                self._blocks.append((re.compile(pattern, re.IGNORECASE | re.DOTALL), category, severity, message))
            except re.error:
                pass

    def check(self, code: str, language: str = "python") -> PreCheckResult:
        if not code or not code.strip():
            return PreCheckResult(decision=PreCheckDecision.CLEAN.value,
                                  original_code=code, final_code=code, language=language)

        original = code
        current = code
        issues = []
        auto_fixes = 0

        # ── Layer 1: Block ──
        for regex, category, severity, message in self._blocks:
            m = regex.search(current)
            if m:
                issues.append(PreCheckIssue(
                    severity=severity, category=category,
                    line=self._find_line(current, m.start()),
                    column=m.start(), message=message,
                    snippet=m.group(0)[:100],
                ))

        if any(i.severity == "critical" for i in issues):
            return PreCheckResult(
                decision=PreCheckDecision.BLOCK.value,
                original_code=original, final_code=original, issues=issues,
                blocks_count=sum(1 for i in issues if i.severity == "critical"),
                language=language,
            )

        # ── Layer 2: Auto-fix ──
        if self.auto_fix_enabled:
            for fix in self._auto_fixes:
                matches = list(fix["regex"].finditer(current))
                if matches:
                    current = fix["regex"].sub(fix["replacement"], current)
                    auto_fixes += len(matches)
                    for m in matches:
                        issues.append(PreCheckIssue(
                            severity=fix["severity"], category=fix["category"],
                            line=self._find_line(original, m.start()),
                            column=m.start(), message=fix["message"],
                            snippet=m.group(0)[:100],
                            auto_fixable=True,
                            suggested_fix=fix["replacement"][:100],
                        ))

        # ── Layer 3: Warnings ──
        for regex, category, severity, message in self._warnings:
            for m in regex.finditer(current):
                issues.append(PreCheckIssue(
                    severity=severity, category=category,
                    line=self._find_line(current, m.start()),
                    column=m.start(), message=message,
                    snippet=m.group(0)[:100],
                ))

        # ── Layer 4: AST checks ──
        if language == "python":
            issues.extend(self._ast_check(current))

        # ── Decision ──
        warnings_count = sum(1 for i in issues if not i.auto_fixable)
        if not issues:
            decision = PreCheckDecision.CLEAN.value
        elif auto_fixes > 0 and warnings_count == 0:
            decision = PreCheckDecision.AUTO_FIXED.value
        elif any(i.severity in ["critical", "high"] for i in issues if not i.auto_fixable):
            decision = PreCheckDecision.BLOCK.value
        else:
            decision = PreCheckDecision.WARN.value

        return PreCheckResult(
            decision=decision, original_code=original, final_code=current,
            issues=issues, auto_fixes_applied=auto_fixes,
            warnings_count=warnings_count,
            blocks_count=sum(1 for i in issues if i.severity == "critical"),
            language=language,
        )

    def _find_line(self, code: str, pos: int) -> int:
        return code[:pos].count("\n") + 1

    def _ast_check(self, code: str) -> List[PreCheckIssue]:
        issues = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return issues

        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                issues.append(PreCheckIssue(
                    severity="low", category="bare_except",
                    line=node.lineno, column=node.col_offset,
                    message="Bare 'except:' catches everything (use 'except Exception')",
                    auto_fixable=False,
                ))
        return issues

    def explain(self, result: PreCheckResult) -> str:
        lines = [f"Pre-Check: {result.decision.upper()}"]
        if not result.issues:
            lines.append("  No issues found")
            return "\n".join(lines)
        if result.auto_fixes_applied:
            lines.append(f"  {result.auto_fixes_applied} auto-fixes applied")
        by_sev = {}
        for i in result.issues:
            by_sev.setdefault(i.severity, []).append(i)
        for sev in ["critical", "high", "medium", "low"]:
            if sev in by_sev:
                lines.append(f"  [{sev.upper()}] {len(by_sev[sev])} issues:")
                for i in by_sev[sev][:3]:
                    tag = " [fixed]" if i.auto_fixable else ""
                    lines.append(f"    line {i.line}: {i.message}{tag}")
        return "\n".join(lines)


pre_check = SecurityPreCheck()

__all__ = ["SecurityPreCheck", "PreCheckResult", "PreCheckIssue", "PreCheckDecision", "pre_check"]
