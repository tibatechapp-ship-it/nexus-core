"""Mini eval runner — يشغّل dataset عبر sandbox."""
import json, subprocess, sys
from pathlib import Path

DATASET = Path(__file__).parent.parent / "datasets" / "mini_python.jsonl"


def run_case(case: dict) -> dict:
    code = case.get("code", "")
    test = case.get("test", "")
    if not code:
        return {"id": case["id"], "passed": False, "error": "no code"}
    
    script = f"{code}\n\n{test}"
    try:
        r = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=10,
        )
        return {
            "id": case["id"],
            "passed": r.returncode == 0,
            "stdout": r.stdout[:200],
            "stderr": r.stderr[:200],
        }
    except subprocess.TimeoutExpired:
        return {"id": case["id"], "passed": False, "error": "timeout"}


def main():
    cases = [json.loads(l) for l in DATASET.read_text().splitlines() if l.strip()]
    passed = 0
    for c in cases:
        r = run_case(c)
        status = "✅" if r["passed"] else "❌"
        print(f"{status} {r['id']}")
        passed += int(r["passed"])
    print(f"\n{passed}/{len(cases)} passed")


if __name__ == "__main__":
    main()
