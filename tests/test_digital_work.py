from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.digital_work.pipeline import (
    create_sample_inputs,
    execute_run,
    run_demo,
    validate_run,
)


def test_demo_executes_thirty_files_and_preserves_first_run(tmp_path: Path) -> None:
    result = run_demo(tmp_path / "proof")
    assert result["sample_files_created"] == 30
    assert result["clean_run"]["input_errors"] == 0
    assert result["corrupted_run"]["input_errors"] == 1
    assert result["previous_run_preserved"] is True
    assert result["clean_run"]["validation"]["valid"] is True
    assert result["corrupted_run"]["validation"]["valid"] is True
    assert (tmp_path / "proof/runs/clean/report.docx").is_file()
    assert (tmp_path / "proof/runs/clean/analysis.xlsx").is_file()


def test_validate_detects_audit_tampering(tmp_path: Path) -> None:
    inputs = create_sample_inputs(tmp_path / "inputs")
    output = tmp_path / "run"
    execute_run(inputs, output, run_id="tamper-test")
    audit = output / "audit.jsonl"
    audit.write_text(audit.read_text(encoding="utf-8").replace("run_started", "run_altered"), encoding="utf-8")
    with pytest.raises(ValueError, match="audit digest mismatch"):
        validate_run(output)


def test_run_refuses_to_overwrite_previous_evidence(tmp_path: Path) -> None:
    inputs = create_sample_inputs(tmp_path / "inputs")
    output = tmp_path / "run"
    execute_run(inputs, output, run_id="first")
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        execute_run(inputs, output, run_id="second")


def test_sensitive_files_are_rejected(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / ".env.production").write_text("TOKEN=not-a-real-secret", encoding="utf-8")
    with pytest.raises(PermissionError, match="sensitive input refused"):
        execute_run(inputs, tmp_path / "run", run_id="sensitive")


def test_symlink_inputs_are_rejected(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    target = tmp_path / "outside.txt"
    target.write_text("outside", encoding="utf-8")
    (inputs / "link.txt").symlink_to(target)
    with pytest.raises(ValueError, match="symlink refused"):
        execute_run(inputs, tmp_path / "run", run_id="symlink")


def test_evidence_records_csv_extraction_errors(tmp_path: Path) -> None:
    inputs = create_sample_inputs(tmp_path / "inputs")
    (inputs / "sales-01.csv").write_text("item,quantity,unit_price\nbroken,nope\n", encoding="utf-8")
    evidence = execute_run(inputs, tmp_path / "run", run_id="bad-csv")
    assert len(evidence["errors"]) == 1
    stored = json.loads((tmp_path / "run/evidence.json").read_text(encoding="utf-8"))
    assert stored["input_count"] == 30
    assert stored["independent_validation"]["valid"] is True
