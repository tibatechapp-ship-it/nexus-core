"""Deterministic pass/fail judge — يقارن stdout بـ reference."""


def judge(case: dict, actual_output: str) -> dict:
    expected = case.get("expected", "")
    passed = expected.strip() in actual_output.strip() if expected else True
    return {
        "id": case["id"],
        "passed": passed,
        "expected": expected[:100],
        "actual": actual_output[:100],
    }
