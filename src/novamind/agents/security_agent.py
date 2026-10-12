"""
Security Agent — Detects vulnerabilities using OWASP patterns.
Pure Python (no LLM for speed) + LLM for complex cases.
"""
import logging
import re
import ast
from typing import Dict, List

logger = logging.getLogger("agents.security_agent")


class SecurityAgent:

    def __init__(self):
        self.name = "security"
    """Detects security vulnerabilities in code."""

    # OWASP Top 10 - Pattern-based
    PATTERNS = {
        # Injection
        "sql_injection": {
            "python": [
                (r'execute\s*\(\s*f["\']', "SQL via f-string — use parameterized queries"),
                (r'execute\s*\(\s*["\'].*%s.*["\']\s*%', "SQL via % — use parameters"),
                (r'execute\s*\(\s*["\'].*\+\s*\w+', "SQL concatenation — use parameters"),
                (r'\.raw\s*\(', "Django raw SQL — validate input"),
            ],
            "javascript": [
                (r'query\s*\(\s*`[^`]*\$\{', "SQL template literal — use parameters"),
            ],
        },
        # XSS
        "xss": {
            "javascript": [
                (r'dangerouslySetInnerHTML', "React XSS risk — sanitize input"),
                (r'\.innerHTML\s*=', "Direct innerHTML — use textContent"),
                (r'document\.write\s*\(', "document.write — use DOM methods"),
                (r'eval\s*\(', "eval() — avoid"),
            ],
            "python": [
                (r'\|\s*safe\b', "Django |safe — XSS risk"),
                (r'mark_safe\s*\(', "Django mark_safe — validate"),
                (r'render_template_string\s*\(', "Flask render_template_string — avoid user input"),
            ],
        },
        # Hardcoded secrets
        "hardcoded_secret": {
            "any": [
                (r'(?:password|passwd|pwd)\s*=\s*["\'][^"\']{8,}["\']', "Hardcoded password"),
                (r'(?:api_key|apikey|secret|token)\s*=\s*["\'][A-Za-z0-9_\-]{20,}["\']', "Hardcoded API key"),
                (r'(?:AWS|aws)_(?:ACCESS|SECRET)[A-Z_]*\s*=\s*["\'][^"\']+["\']', "Hardcoded AWS key"),
                (r'-----BEGIN (?:RSA )?PRIVATE KEY-----', "Private key in code"),
            ],
        },
        # Weak crypto
        "weak_crypto": {
            "any": [
                (r'\bmd5\s*\(', "MD5 — use SHA-256+"),
                (r'\bsha1\s*\(', "SHA-1 — use SHA-256+"),
                (r'\bdes\s*\(', "DES — use AES"),
                (r'random\.random\s*\(', "random for security — use secrets"),
                (r'random\.randint\s*\(', "random for security — use secrets"),
            ],
        },
        # Insecure deserialization
        "insecure_deser": {
            "python": [
                (r'pickle\.loads?\s*\(', "pickle — use JSON"),
                (r'yaml\.load\s*\([^,)]+\)(?!\s*,\s*Loader)', "yaml.load unsafe — use safe_load"),
                (r'marshal\.loads?\s*\(', "marshal — unsafe"),
            ],
            "javascript": [
                (r'JSON\.parse\s*\(\s*.*eval', "Risky JSON parse"),
            ],
        },
        # Path traversal
        "path_traversal": {
            "any": [
                (r'open\s*\([^,)]*\+\s*\w+', "User-controlled path — validate"),
                (r'os\.path\.join\s*\([^)]*request', "User path in join — sanitize"),
            ],
        },
        # Command injection
        "cmd_injection": {
            "python": [
                (r'os\.system\s*\(', "os.system — use subprocess with list"),
                (r'subprocess\.(?:run|call|Popen)\s*\([^)]*shell\s*=\s*True', "shell=True — use list args"),
                (r'os\.popen\s*\(', "os.popen — use subprocess"),
            ],
            "javascript": [
                (r'child_process\.exec\s*\(', "exec with user input — use spawn"),
            ],
        },
        # CSRF
        "csrf": {
            "python": [
                (r'@app\.route.*methods\s*=\s*\[.*POST', "Flask POST — need CSRF protection"),
            ],
        },
        # Auth issues
        "auth_issues": {
            "any": [
                (r'if\s+\w+\s*==\s*["\']admin["\']', "Hardcoded admin check — use RBAC"),
                (r'\.decode\s*\(\s*["\']base64["\']\s*\).*password', "Base64 for password — use hash"),
            ],
        },
    }

    SEVERITY_MAP = {
        "sql_injection": "critical",
        "cmd_injection": "critical",
        "insecure_deser": "critical",
        "hardcoded_secret": "critical",
        "xss": "high",
        "path_traversal": "high",
        "weak_crypto": "high",
        "auth_issues": "high",
        "csrf": "medium",
    }

    def detect_lang(self, filename: str) -> str:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext == "py":
            return "python"
        if ext in ("js", "jsx", "ts", "tsx"):
            return "javascript"
        return "any"

    def analyze(self, code: str, filename: str = "code.py") -> Dict:
        """Analyze code for security vulnerabilities."""
        if not code or not code.strip():
            return {"ok": True, "verdict": "ok", "issues": [], "total": 0}

        lang = self.detect_lang(filename)
        issues = []
        lines = code.split("\n")

        # Scan each pattern
        for category, langs in self.PATTERNS.items():
            patterns = []
            if lang in langs:
                patterns = langs[lang]
            elif "any" in langs:
                patterns = langs["any"]

            for pattern, desc in patterns:
                try:
                    regex = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
                except re.error:
                    continue

                for i, line in enumerate(lines, 1):
                    # Skip comments
                    stripped = line.strip()
                    if stripped.startswith(("#", "//")):
                        continue

                    if regex.search(line):
                        issues.append({
                            "line": i,
                            "severity": self.SEVERITY_MAP.get(category, "medium"),
                            "category": category,
                            "description": desc,
                            "snippet": stripped[:100],
                        })
        # Additional AST checks for Python
        if lang == "python":
            issues.extend(self._python_ast_checks(code))

        # Deduplicate
        seen = set()
        unique = []
        for issue in issues:
            key = (issue["line"], issue["category"])
            if key not in seen:
                seen.add(key)
                unique.append(issue)

        # Verdict
        if any(i["severity"] == "critical" for i in unique):
            verdict = "broken"
        elif unique:
            verdict = "issues"
        else:
            verdict = "ok"

        return {
            "ok": verdict == "ok",
            "verdict": verdict,
            "language": lang,
            "total": len(unique),
            "by_severity": {
                "critical": sum(1 for i in unique if i["severity"] == "critical"),
                "high": sum(1 for i in unique if i["severity"] == "high"),
                "medium": sum(1 for i in unique if i["severity"] == "medium"),
            },
            "issues": unique,
        }

    def _python_ast_checks(self, code: str) -> List[Dict]:
        """AST-based security checks."""
        issues = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return issues

        for node in ast.walk(tree):
            # Check for eval/exec/compile
            if isinstance(node, ast.Call):
                func_name = None
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    if isinstance(node.func.value, ast.Name):
                        func_name = f"{node.func.value.id}.{node.func.attr}"

                dangerous = {
                    "eval": ("SecurityRisk", "eval() — critical"),
                    "exec": ("SecurityRisk", "exec() — critical"),
                    "compile": ("SecurityRisk", "compile() — careful"),
                    "os.system": ("CmdInjection", "os.system — use subprocess list"),
                }

                if func_name in dangerous:
                    cat, desc = dangerous[func_name]
                    issues.append({
                        "line": node.lineno,
                        "severity": "critical" if "critical" in desc else "high",
                        "category": cat.lower(),
                        "description": desc,
                        "snippet": func_name + "()",
                    })

        return issues

    def report(self, result: Dict) -> str:
        """Generate human-readable report."""
        if result.get("verdict") == "ok":
            return "✅ لا توجد ثغرات أمنية"

        lines = [f"🔒 تقرير أمني ({result['total']} مشكلة)"]
        lines.append("")

        by_sev = {"critical": "🚨", "high": "🔴", "medium": "🟡"}

        for severity in ["critical", "high", "medium"]:
            sev_issues = [i for i in result["issues"] if i["severity"] == severity]
            if not sev_issues:
                continue
            lines.append(f"{by_sev[severity]} {severity.upper()}: {len(sev_issues)}")
            for issue in sev_issues[:10]:
                lines.append(f"   L{issue['line']}: {issue['description']}")
            lines.append("")

        return "\n".join(lines)


security_agent = SecurityAgent()
__all__ = ["SecurityAgent", "security_agent"]
