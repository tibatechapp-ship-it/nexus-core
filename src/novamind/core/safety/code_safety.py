"""
Code Safety Utilities — NovaMind v6.5

Three critical functions:

  1. format_text_safely(text, is_code=False)
       Normalizes whitespace, preserves indentation, never translates.

  2. detect_code_errors(code, lang)
       Detects syntax and semantic errors WITHOUT calling LLM.

  3. protect_code(code)
       Replaces string literals with placeholders so LLM cannot
       translate or modify them. Unprotect restores original.

Designed for: preventing NovaMind from breaking code while reviewing.
"""
import re
import ast
import logging
from typing import Dict, List, Tuple

logger = logging.getLogger("safety.code_safety")


# ═══════════════════════════════════════════════════════════════
#  1. FORMAT TEXT SAFELY
# ═══════════════════════════════════════════════════════════════

def format_text_safely(text: str, is_code: bool = False) -> str:
    """
    Format text without breaking anything.

    If is_code=True:
        - Preserve indentation exactly
        - Only strip trailing whitespace per line
        - Convert CRLF → LF
        - Ensure single trailing newline

    If is_code=False (natural text):
        - Collapse multiple spaces
        - Normalize newlines
        - Trim leading/trailing space

    NEVER translates, NEVER modifies identifiers.
    """
    if not text:
        return ""

    # Universal: normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    if is_code:
        # Only trim trailing whitespace on each line
        lines = [line.rstrip() for line in text.split("\n")]
        result = "\n".join(lines)
        # Ensure single trailing newline
        result = result.rstrip("\n") + "\n"
        return result
    else:
        # Natural text: collapse spaces
        lines = []
        for line in text.split("\n"):
            line = re.sub(r"[ \t]+", " ", line).strip()
            lines.append(line)
        result = "\n".join(lines)
        return result.strip()


# ═══════════════════════════════════════════════════════════════
#  2. DETECT CODE ERRORS (no LLM)
# ═══════════════════════════════════════════════════════════════

def detect_code_errors(code: str, lang: str = "python") -> Dict:
    """
    Detect errors WITHOUT using an LLM.
    Returns: {"ok": bool, "errors": [{"line": int, "type": str, "msg": str}]}
    """
    if not code or not code.strip():
        return {"ok": True, "errors": []}

    errors = []

    if lang == "python" or code.lstrip().startswith(("import ", "def ", "class ", "#")):
        errors = _detect_python_errors(code)
    elif lang in ("javascript", "typescript", "js", "ts", "jsx", "tsx"):
        errors = _detect_js_errors(code)
    else:
        # Generic: check for common issues
        errors = _detect_generic_errors(code)

    return {"ok": len(errors) == 0, "errors": errors}


def _detect_python_errors(code: str) -> List[Dict]:
    """Python errors via AST + regex."""
    errors = []

    # 1. Syntax check via AST
    try:
        ast.parse(code)
    except SyntaxError as e:
        errors.append({
            "line": e.lineno or 0,
            "col": e.offset or 0,
            "type": "SyntaxError",
            "msg": str(e.msg)[:200],
        })
        # If syntax is broken, skip semantic checks
        return errors

    # 2. Common semantic issues (regex-based, cheap)
    lines = code.split("\n")
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Skip comments and strings
        if stripped.startswith("#"):
            continue

        # = (single equals) in if/while condition
        if re.search(r"\b(if|while)\s+.*[^=!<>]=[^=]", line):
            errors.append({
                "line": i, "type": "Warning",
                "msg": "Possible assignment in condition (use == ?)",
            })

        # eval/exec — security
        if re.search(r"\b(eval|exec)\s*\(", line):
            errors.append({
                "line": i, "type": "Security",
                "msg": "eval/exec detected — potential security risk",
            })

        # bare except
        if re.match(r"^\s*except\s*:", line):
            errors.append({
                "line": i, "type": "Warning",
                "msg": "bare 'except:' — catches all exceptions, prefer explicit",
            })

        # TODO/FIXME
        if re.search(r"#\s*(TODO|FIXME|XXX)", line, re.IGNORECASE):
            errors.append({
                "line": i, "type": "Note",
                "msg": stripped[:120],
            })

    return errors


def _detect_js_errors(code: str) -> List[Dict]:
    """Basic JS/TS checks (regex-based, no full parser)."""
    errors = []
    lines = code.split("\n")

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("//"):
            continue

        # var usage
        if re.search(r"\bvar\s+\w+", line):
            errors.append({
                "line": i, "type": "Warning",
                "msg": "use 'let' or 'const' instead of 'var'",
            })

        # == instead of ===
        if re.search(r"[^=!<>]==[^=]", line):
            errors.append({
                "line": i, "type": "Warning",
                "msg": "use '===' instead of '=='",
            })

        # console.log
        if re.search(r"\bconsole\.log\s*\(", line):
            errors.append({
                "line": i, "type": "Warning",
                "msg": "console.log() found — remove in production",
            })

        # Arabic in JSX without dir
        if re.search(r">[\s]*[\u0600-\u06FF]", line) and "dir=" not in line:
            errors.append({
                "line": i, "type": "Warning",
                "msg": "Arabic text in JSX — consider dir='rtl'",
            })

    return errors


def _detect_generic_errors(code: str) -> List[Dict]:
    """Generic checks for any text/code."""
    errors = []
    lines = code.split("\n")
    for i, line in enumerate(lines, 1):
        if re.search(r"#\s*(TODO|FIXME)", line, re.IGNORECASE):
            errors.append({
                "line": i, "type": "Note",
                "msg": line.strip()[:120],
            })
    return errors


# ═══════════════════════════════════════════════════════════════
#  3. PROTECT CODE FROM LLM
# ═══════════════════════════════════════════════════════════════

# Placeholder format: ___STR_N___
PLACEHOLDER_RE = re.compile(r"___STR_(\d+)___")
STRING_RE = re.compile(
    r'("""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')',
    re.MULTILINE,
)


def protect_code(code: str) -> Tuple[str, List[str]]:
    """
    Replace string literals with placeholders so LLM cannot translate them.
    Returns: (protected_code, original_strings)
    """
    originals: List[str] = []

    def _repl(m):
        idx = len(originals)
        originals.append(m.group(0))
        return f"___STR_{idx}___"

    protected = STRING_RE.sub(_repl, code)
    return protected, originals


def unprotect_code(text: str, originals: List[str]) -> str:
    """Restore original strings from placeholders."""
    def _repl(m):
        idx = int(m.group(1))
        if 0 <= idx < len(originals):
            return originals[idx]
        return m.group(0)

    return PLACEHOLDER_RE.sub(_repl, text)


def has_placeholders(text: str) -> bool:
    """Check if text contains placeholders."""
    return bool(PLACEHOLDER_RE.search(text))


def integrity_check(original: str, modified: str, is_code: bool = True) -> Dict:
    """
    Verify modified code hasn't been broken.
    Returns: {"ok": bool, "issues": [...]}
    """
    issues = []

    if not modified or not modified.strip():
        return {"ok": False, "issues": [{"type": "empty", "msg": "output is empty"}]}

    # 1. If original was valid Python, modified should be too
    if is_code and original:
        try:
            ast.parse(original)
            original_valid = True
        except SyntaxError:
            original_valid = False

        if original_valid:
            try:
                ast.parse(modified)
            except SyntaxError as e:
                issues.append({
                    "type": "syntax_broken",
                    "msg": f"modified code has SyntaxError: {e.msg} (line {e.lineno})",
                })

    # 2. Check for unintended translations
    original_arabic = len(re.findall(r"[\u0600-\u06FF]", original))
    modified_arabic = len(re.findall(r"[\u0600-\u06FF]", modified))
    if original_arabic > 0 and modified_arabic == 0 and "___STR_" not in modified:
        issues.append({
            "type": "arabic_lost",
            "msg": f"original had {original_arabic} Arabic chars, modified has 0",
        })

    # 3. Check for lost placeholders
    if has_placeholders(original) and not has_placeholders(modified):
        issues.append({
            "type": "placeholders_lost",
            "msg": "modified lost placeholders (LLM may have modified protected regions)",
        })

    return {"ok": len(issues) == 0, "issues": issues}


# ═══════════════════════════════════════════════════════════════
#  High-level safe wrapper for LLM calls
# ═══════════════════════════════════════════════════════════════

def safe_llm_analyze(code: str, llm_call_fn, lang: str = "python") -> Dict:
    """
    Wrap an LLM call so it NEVER breaks the code.

    1. Detect errors locally first.
    2. Protect strings.
    3. Call LLM.
    4. Unprotect strings.
    5. Verify integrity.
    6. Return: {"ok", "errors", "analysis", "issues"}
    """
    # Step 1: local error detection
    local_errors = detect_code_errors(code, lang)

    # Step 2: protect strings
    protected, originals = protect_code(code)

    # Step 3: LLM call
    try:
        llm_output = llm_call_fn(protected)
    except Exception as e:
        return {
            "ok": False,
            "errors": local_errors["errors"],
            "analysis": "",
            "issues": [{"type": "llm_failed", "msg": str(e)[:200]}],
        }

    # Step 4: unprotect
    restored = unprotect_code(llm_output, originals)

    # Step 5: integrity check
    integrity = integrity_check(code, restored, is_code=True)

    return {
        "ok": integrity["ok"],
        "errors": local_errors["errors"],
        "analysis": restored,
        "issues": integrity["issues"],
    }
