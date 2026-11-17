"""Cross-language static intelligence tests; no repository code is executed."""
from __future__ import annotations

from pathlib import Path

from src.coder.detector import MAX_SOURCE_BYTES, static_scan


def test_static_scan_detects_typescript_and_go_security_signals(tmp_path: Path) -> None:
    (tmp_path / "web.ts").write_text(
        "const run = (source: string) => eval(source);\n"
        "const client = { rejectUnauthorized: false };\n",
        encoding="utf-8",
    )
    (tmp_path / "server.go").write_text(
        "tlsConfig := &tls.Config{InsecureSkipVerify: true}\n",
        encoding="utf-8",
    )

    findings = static_scan(tmp_path)
    by_rule = {(item["file"], item["rule_id"]): item for item in findings}

    assert ("web.ts", "dynamic-evaluation") in by_rule
    assert ("web.ts", "tls-verification-disabled") in by_rule
    assert ("server.go", "tls-verification-disabled") in by_rule
    assert by_rule[("web.ts", "dynamic-evaluation")]["line"] == 1
    assert all(item["source"] == "static" for item in findings)


def test_static_scan_redacts_possible_credentials(tmp_path: Path) -> None:
    secret_value = "super-secret-value-123"
    (tmp_path / "settings.py").write_text(
        f'api_key = "{secret_value}"\n',
        encoding="utf-8",
    )

    findings = static_scan(tmp_path)

    assert len(findings) == 1
    assert findings[0]["rule_id"] == "hardcoded-credential"
    assert secret_value not in str(findings[0])
    assert findings[0]["line"] == 1


def test_static_scan_handles_javascript_shell_risk_and_markers(tmp_path: Path) -> None:
    (tmp_path / "runner.js").write_text(
        "child_process.exec(userInput); // FIXME validate input\n",
        encoding="utf-8",
    )

    findings = static_scan(tmp_path)
    rules = {item["rule_id"] for item in findings}

    assert "shell-execution" in rules
    assert "fixme" in rules


def test_static_scan_skips_hidden_generated_and_sensitive_paths(tmp_path: Path) -> None:
    for directory in (".git", ".venv", "node_modules", "secrets", "private"):
        target = tmp_path / directory
        target.mkdir()
        (target / "leak.ts").write_text(
            "eval(untrusted); // TODO\n",
            encoding="utf-8",
        )
    (tmp_path / "visible.txt").write_text("TODO", encoding="utf-8")

    assert static_scan(tmp_path) == []


def test_static_scan_is_bounded_and_nonpositive_limit_is_empty(tmp_path: Path) -> None:
    (tmp_path / "large.py").write_text(
        "x = 1\n" * (MAX_SOURCE_BYTES // 2),
        encoding="utf-8",
    )
    (tmp_path / "small.py").write_text("TODO\nFIXME\n", encoding="utf-8")

    assert static_scan(tmp_path, limit=0) == []
    assert len(static_scan(tmp_path, limit=1)) == 1
    assert len(static_scan(tmp_path, limit=10)) == 2
