# Rule: English-First Python Code (Pragmatic)

**Status:** Active **Enforced by:** `scripts/git-hooks/pre-commit` (advisory) **Established:**
2026-10-08

## Policy

To balance code quality with Arabic UX requirements, we use a pragmatic rule.

### FORBIDDEN

- Arabic/CJK/Cyrillic/Hebrew in identifiers (variable/function/class names)
- Non-ASCII in import statements
- Non-ASCII outside string literals and comments

### ALLOWED

- Arabic in string literals (user-facing text, regex patterns, messages)
- Arabic in comments (documentation)
- Emoji anywhere (safe, informative)
- Non-ASCII in docs/\*\*, *.json, tests/fixtures/*\*

## Rationale

The system intentionally supports Arabic for:

- Task planning (task_planner.py uses Arabic regex)
- MoE routing (moe_router.py uses Arabic keywords)
- UI messages (main.py, welcome_messages.py)
- Agent reports

Removing Arabic would break the product.

## Enforcement

The pre-commit hook is advisory only (not blocking) for existing files.

For new files, we recommend following the style guide.

## Example: GOOD

String literals and comments can contain Arabic:

```
WELCOME_MESSAGE = "WELCOME_MESSAGE_IN_ARABIC"
ARABIC_PATTERN = r"PATTERN_WITH_ARABIC_KEYWORDS"

def analyze_code(code: str) -> dict:
    # Comment in Arabic is allowed
    return {"status": "success"}
```

## Example: BAD

Identifiers must be ASCII:

```
arabic_var = lambda x: x   # WRONG: identifier not ASCII
from arabic_module import y  # WRONG: import not ASCII
```

## Migration Policy

- Existing files: no forced migration
- New files: follow guidelines
- Refactors: translate identifiers to English when touching code

## References

- PEP 3131: Supporting Non-ASCII Identifiers (Python 3)
- Our system: 173 files with Arabic content (intentional)
