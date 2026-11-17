from __future__ import annotations

from pathlib import Path

from src.coder.context import build_code_context


def test_context_includes_defect_file_and_direct_python_imports(tmp_path: Path) -> None:
    app_source = "\n".join([
        "from helpers import normalize",
        "",
        "def run():",
        "    return normalize(' X ')",
    ])
    (tmp_path / "app.py").write_text(app_source)
    (tmp_path / "helpers.py").write_text("def normalize(value):\n    return value.strip().lower()\n")
    repo = {
        "modules": [
            {"path": "app.py", "name": "app", "imports": ["helpers"], "loc": 4},
            {"path": "helpers.py", "name": "helpers", "imports": [], "loc": 2},
        ]
    }

    result = build_code_context(
        tmp_path, repo, [{"file": "app.py", "description": "bug", "severity": "high"}]
    )

    assert result["files"] == ["app.py", "helpers.py"]
    assert "return normalize(' X ')" in result["rendered"]
    assert "return value.strip().lower()" in result["rendered"]


def test_context_rejects_traversal_and_sensitive_files(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.py"
    outside.write_text("secret = 'must not be read'")
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "config.py").write_text("TOKEN = 'private'")
    (tmp_path / "safe.py").write_text("def safe():\n    return True\n")

    result = build_code_context(
        tmp_path,
        {},
        [{"file": "../outside.py"}, {"file": "secrets/config.py"}, {"file": "safe.py"}],
    )

    assert result["files"] == ["safe.py"]
    assert "must not be read" not in result["rendered"]
    assert "TOKEN" not in result["rendered"]


def test_context_enforces_file_and_total_budgets(tmp_path: Path) -> None:
    for name in ("a.py", "b.py", "c.py"):
        (tmp_path / name).write_text("x" * 100)

    result = build_code_context(
        tmp_path,
        {},
        [{"file": "a.py"}, {"file": "b.py"}, {"file": "c.py"}],
        max_files=2,
        max_file_bytes=80,
        max_total_chars=100,
    )

    assert len(result["files"]) <= 2
    assert result["characters"] <= 100
    assert result["truncated"] is True



def test_lexical_retrieval_finds_related_typescript_without_defect_path(tmp_path: Path) -> None:
    (tmp_path / "payments.ts").write_text(
        "export function reconcileInvoice(idempotencyKey: string): boolean { "
        "return Boolean(idempotencyKey); }"
    )
    (tmp_path / "profile.ts").write_text(
        "export function updateProfile(displayName: string): string { "
        "return displayName.trim(); }"
    )
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "invoice.ts").write_text(
        "export const invoiceIdempotencyKey = 'private';"
    )

    result = build_code_context(
        tmp_path,
        {},
        [],
        goal="repair invoice idempotency reconciliation",
    )

    assert result["files"] == ["payments.ts"]
    assert "reconcileInvoice" in result["rendered"]
    assert "secrets/invoice.ts" not in result["rendered"]
    assert result["retrieval"] == "bm25_lexical"
