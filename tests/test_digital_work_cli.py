from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from src.digital_work import cli


def _invoke(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> tuple[int, str]:
    from io import StringIO
    from contextlib import redirect_stdout

    monkeypatch.setattr(sys, "argv", argv)
    output = StringIO()
    with redirect_stdout(output):
        code = cli.main()
    return code, output.getvalue()


def test_cli_demo_dispatch_and_json_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output_dir = tmp_path / "demo"
    monkeypatch.setattr(cli, "run_demo", lambda output: {"mode": "demo", "path": str(output)})
    code, output = _invoke(
        monkeypatch, ["nexus-digital-work", "demo", "--output", str(output_dir)]
    )
    assert code == 0
    assert json.loads(output) == {"mode": "demo", "path": str(output_dir)}


def test_cli_run_dispatches_input_output_and_run_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source, output_dir = tmp_path / "input", tmp_path / "output"
    calls: list[tuple[Path, Path, str]] = []
    monkeypatch.setattr(
        cli, "execute_run",
        lambda input_dir, output, run_id: (
            calls.append((input_dir, output, run_id)) or {"mode": "run"}
        ),
    )
    code, output = _invoke(
        monkeypatch,
        ["nexus-digital-work", "run", str(source), "--output", str(output_dir), "--run-id", "case-7"],
    )
    assert code == 0
    assert calls == [(source, output_dir, "case-7")]
    assert json.loads(output) == {"mode": "run"}


def test_cli_validate_dispatches_run_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_dir = tmp_path / "previous-run"
    monkeypatch.setattr(cli, "validate_run", lambda path: {"valid": path == run_dir})
    code, output = _invoke(
        monkeypatch, ["nexus-digital-work", "validate", str(run_dir)]
    )
    assert code == 0
    assert json.loads(output) == {"valid": True}


def test_cli_requires_a_subcommand(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["nexus-digital-work"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
