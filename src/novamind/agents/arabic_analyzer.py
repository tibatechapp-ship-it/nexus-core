"""
Arabic Language Analyzer - Detection, validation, and improvement
"""
import re
import json
import logging
import sys
from typing import Dict, List
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger("agents.arabic")


# ─── Arabic character ranges ─────────────────────
ARABIC_RANGE = re.compile(r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]')
ARABIC_PRESENTATION_FORMS = re.compile(r'[\uFB50-\uFDFF\uFE70-\uFEFF]')
TASHKEEL = re.compile(r'[\u064B-\u0652\u0670\u0640]')
ARABIC_NUMERALS = re.compile(r'[\u0660-\u0669\u06F0-\u06F9]')


def contains_arabic(text: str) -> bool:
    return bool(ARABIC_RANGE.search(text))


def arabic_ratio(text: str) -> float:
    if not text:
        return 0.0
    arabic_count = len(ARABIC_RANGE.findall(text))
    return arabic_count / len(text)


# ─── Arabic specific checks ─────────────────────
def check_python_arabic(code: str) -> List[Dict]:
    """Checks Arabic-specific issues in Python code."""
    issues = []
    lines = code.split("\n")

    # 1. Arabic strings without explicit encoding declaration
    has_arabic_strings = False
    has_encoding_decl = False
    for i, line in enumerate(lines, 1):
        if "coding:" in line or "coding=" in line:
            has_encoding_decl = True
        # Arabic in string literal
        if contains_arabic(line) and ('"' in line or "'" in line):
            has_arabic_strings = True

    if has_arabic_strings and not has_encoding_decl:
        issues.append({
            "type": "i18n",
            "line": 1,
            "description": "Arabic strings found without '# -*- coding: utf-8 -*-' declaration",
            "severity": "warning",
        })

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # 2. print() with Arabic without encoding
        if "print(" in stripped and contains_arabic(stripped):
            if "encoding" not in stripped.lower():
                issues.append({
                    "type": "i18n",
                    "line": i,
                    "description": "Arabic print() may fail on non-UTF-8 systems - use sys.stdout.reconfigure(encoding='utf-8')",
                    "severity": "warning",
                })

        # 3. Open files with Arabic without encoding
        if re.search(r'open\s*\(', stripped) and contains_arabic(stripped):
            if "encoding=" not in stripped:
                issues.append({
                    "type": "i18n",
                    "line": i,
                    "description": "open() with Arabic content needs encoding='utf-8'",
                    "severity": "warning",
                })

        # 4. Arabic in file paths
        if contains_arabic(stripped) and any(kw in stripped for kw in ["path", "Path", "open"]):
            if "encode" not in stripped and "encoding" not in stripped:
                issues.append({
                    "type": "i18n",
                    "line": i,
                    "description": "Arabic in file paths may cause issues - use Path objects",
                    "severity": "info",
                })

        # 5. Inconsistent Tashkeel usage
        if contains_arabic(stripped) and ('"' in stripped or "'" in stripped):
            tashkeel_count = len(TASHKEEL.findall(stripped))
            arabic_chars = len(ARABIC_RANGE.findall(stripped))
            if arabic_chars > 20 and tashkeel_count > 0 and tashkeel_count < arabic_chars * 0.05:
                issues.append({
                    "type": "i18n",
                    "line": i,
                    "description": "Inconsistent Tashkeel in Arabic string",
                    "severity": "info",
                })

    return issues


def check_typescript_arabic(code: str) -> List[Dict]:
    """Checks Arabic-specific issues in TypeScript/JavaScript."""
    issues = []
    lines = code.split("\n")

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # 1. Arabic in string literals without proper encoding
        if contains_arabic(stripped) and ('"' in stripped or "'" in stripped or '`' in stripped):
            # Check if it's in JSX/HTML without dir
            if "dir=" not in stripped and ("<" in stripped and ">" in stripped):
                issues.append({
                    "type": "i18n",
                    "line": i,
                    "description": "Arabic text in JSX/HTML should have dir='rtl'",
                    "severity": "warning",
                })

        # 2. Arabic in console.log
        if "console.log" in stripped and contains_arabic(stripped):
            issues.append({
                "type": "i18n",
                "line": i,
                "description": "Arabic in console.log may show incorrectly in some terminals",
                "severity": "info",
            })

        # 3. Arabic strings without proper bidi isolation
        if contains_arabic(stripped) and '"' in stripped:
            arabic_str = re.search(r'"([^"]*)"', stripped)
            if arabic_str:
                text = arabic_str.group(1)
                # Check if it mixes Arabic and Latin
                has_arabic = bool(ARABIC_RANGE.search(text))
                has_latin = bool(re.search(r'[A-Za-z]', text))
                if has_arabic and has_latin:
                    if '\u202A' not in text and '\u2066' not in text:
                        issues.append({
                            "type": "i18n",
                            "line": i,
                            "description": "Mixed Arabic/Latin text may display incorrectly - consider bidi isolation",
                            "severity": "info",
                        })

        # 4. Arabic in URLs
        if ("http://" in stripped or "https://" in stripped) and contains_arabic(stripped):
            issues.append({
                "type": "i18n",
                "line": i,
                "description": "Arabic in URLs must be URL-encoded",
                "severity": "warning",
            })

    return issues


def check_arabic_in_json(code: str) -> List[Dict]:
    """Checks Arabic handling in JSON."""
    issues = []
    try:
        data = json.loads(code)
    except Exception:
        return []

    def walk(obj, path=""):
        found = []
        if isinstance(obj, str):
            if contains_arabic(obj):
                # Check for presentation forms
                if ARABIC_PRESENTATION_FORMS.search(obj):
                    found.append({
                        "type": "i18n",
                        "line": 0,
                        "path": path,
                        "description": "Arabic presentation forms found - use canonical forms",
                        "severity": "warning",
                    })
        elif isinstance(obj, dict):
            for k, v in obj.items():
                found.extend(walk(v, f"{path}.{k}"))
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                found.extend(walk(v, f"{path}[{i}]"))
        return found

    return walk(data)


# ─── Main Analyzer ──────────────────────────────
class ArabicAnalyzer:
    def __init__(self):
        self.name = "arabic_analyzer"

    def analyze(self, code: str, filename: str = "file.txt") -> Dict:
        """Analyzes Arabic-specific issues."""
        if not contains_arabic(code):
            return {
                "language": "arabic",
                "verdict": "no_arabic",
                "issues": [],
                "detected_arabic": False,
            }

        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        issues = []

        if ext == "py":
            issues = check_python_arabic(code)
        elif ext in ("ts", "tsx", "js", "jsx"):
            issues = check_typescript_arabic(code)
        elif ext == "json":
            issues = check_arabic_in_json(code)

        # Calculate Arabic ratio
        ratio = arabic_ratio(code)

        return {
            "language": "arabic",
            "verdict": "ok" if not issues else "issues",
            "detected_arabic": True,
            "arabic_ratio": round(ratio, 3),
            "issues": issues,
            "filename": filename,
        }

    def analyze_report(self, results: List[Dict]) -> str:
        """Generates an Arabic report from analysis results."""
        if not results:
            return "لا توجد ملفات للتحليل."

        total_issues = sum(len(r.get("issues", [])) for r in results)
        arabic_files = sum(1 for r in results if r.get("detected_arabic"))

        lines = [
            "# 📊 تقرير NovaMind للغة العربية",
            "",
            f"**الملفات المحللة:** {len(results)}",
            f"**ملفات بها محتوى عربي:** {arabic_files}",
            f"**إجمالي المشاكل:** {total_issues}",
            "",
        ]

        for r in results:
            if not r.get("detected_arabic"):
                continue
            filename = r.get("filename", "?")
            issues = r.get("issues", [])
            ratio = r.get("arabic_ratio", 0)

            if issues:
                lines.append(f"## 📄 `{filename}`")
                lines.append(f"نسبة العربية: {ratio * 100:.1f}%")
                lines.append("")
                for issue in issues:
                    lines.append(f"- ⚠️ سطر {issue.get('line')}: {issue.get('description')}")
                lines.append("")

        if total_issues == 0:
            lines.append("✅ لا توجد مشاكل عربية!")
            lines.append("")

        return "\n".join(lines)


arabic_analyzer = ArabicAnalyzer()
