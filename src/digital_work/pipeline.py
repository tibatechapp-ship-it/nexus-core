"""A reproducible, auditable digital-work pipeline using only the Python stdlib.

The demo creates 30 input files, classifies and extracts them, analyzes CSV data,
writes genuine DOCX/XLSX Office Open XML files, and independently validates outputs.
It never executes input files and refuses symlinks, secret-like files, and oversized inputs.
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

MAX_FILE_BYTES = 1_000_000
SENSITIVE_NAMES = {".env", ".env.local", "credentials.json", "secrets.json"}
DOCX_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XLSX_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
XLSX_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _safe_xml_fromstring(data: bytes) -> ET.Element:
    """Parse Office XML while refusing DTD/entity declarations."""
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("Office XML part exceeds size limit")
    upper = data.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ValueError("DTD/entity declarations are not allowed in Office XML")
    return ET.fromstring(data)  # nosec B314 — DTD/entity declarations rejected above


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_files(root: Path) -> list[Path]:
    base = root.resolve(strict=True)
    files: list[Path] = []
    for candidate in sorted(root.rglob("*")):
        if candidate.is_symlink():
            raise ValueError(f"symlink refused: {candidate}")
        if not candidate.is_file():
            continue
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(base):
            raise ValueError(f"path escapes input root: {candidate}")
        if candidate.name.lower() in SENSITIVE_NAMES or candidate.name.lower().startswith(".env."):
            raise PermissionError(f"sensitive input refused: {candidate.name}")
        if candidate.stat().st_size > MAX_FILE_BYTES:
            raise ValueError(f"input exceeds {MAX_FILE_BYTES} bytes: {candidate.name}")
        files.append(candidate)
    return files


def _write_docx(path: Path, title: str, paragraphs: list[str]) -> None:
    def paragraph(value: str) -> str:
        escaped = (value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        return f'<w:p><w:r><w:t xml:space="preserve">{escaped}</w:t></w:r></w:p>'

    body = paragraph(title) + "".join(paragraph(item) for item in paragraphs)
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{DOCX_NS}"><w:body>{body}'
        '<w:sectPr/></w:body></w:document>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '</Types>'
        ))
        archive.writestr("_rels/.rels", (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '</Relationships>'
        ))
        archive.writestr("word/document.xml", document)


def _column_name(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _write_xlsx(path: Path, rows: list[list[Any]]) -> None:
    sheet_rows: list[str] = []
    for row_index, row in enumerate(rows, start=1):
        cells: list[str] = []
        for column_index, value in enumerate(row, start=1):
            ref = f"{_column_name(column_index)}{row_index}"
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
            else:
                text = (str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>')
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{XLSX_MAIN}"><sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '</Types>'
        ))
        archive.writestr("_rels/.rels", (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>'
        ))
        archive.writestr("xl/workbook.xml", (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<workbook xmlns="{XLSX_MAIN}" xmlns:r="{XLSX_REL}"><sheets>'
            '<sheet name="CSV Analysis" sheetId="1" r:id="rId1"/>'
            '</sheets></workbook>'
        ))
        archive.writestr("xl/_rels/workbook.xml.rels", (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '</Relationships>'
        ))
        archive.writestr("xl/worksheets/sheet1.xml", sheet)


def create_sample_inputs(root: Path) -> Path:
    """Create exactly 30 synthetic, non-sensitive sample files."""
    root.mkdir(parents=True, exist_ok=False)
    for index in range(1, 11):
        (root / f"note-{index:02d}.txt").write_text(
            f"Operations note {index}\nCategory: operations\nStatus: reviewed\n", encoding="utf-8"
        )
        (root / f"record-{index:02d}.md").write_text(
            f"# Record {index}\n\nSynthetic project record {index} for workflow validation.\n",
            encoding="utf-8",
        )
        with (root / f"sales-{index:02d}.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["item", "quantity", "unit_price"])
            writer.writerow([f"item-{index}", index, f"{index * 2}.50"])
            writer.writerow([f"item-{index}-extra", index + 1, f"{index}.25"])
    return root


def _append_audit(path: Path, event: str, detail: dict[str, Any]) -> None:
    previous = ""
    sequence = 0
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
        if lines:
            previous = json.loads(lines[-1])["digest"]
            sequence = len(lines)
    record = {"seq": sequence + 1, "event": event, "detail": detail, "prev": previous}
    payload = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    record["digest"] = _sha256(payload + b"|" + previous.encode())
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")


def _verify_audit(path: Path) -> int:
    previous = ""
    count = 0
    if not path.is_file():
        raise ValueError("audit log missing")
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        record = json.loads(line)
        digest = record.pop("digest", None)
        if record.get("prev") != previous:
            raise ValueError(f"audit chain broken at line {line_number}")
        payload = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        expected = _sha256(payload + b"|" + previous.encode())
        if digest != expected:
            raise ValueError(f"audit digest mismatch at line {line_number}")
        previous = str(digest)
        count += 1
    return count


def execute_run(input_root: Path, output_root: Path, *, run_id: str) -> dict[str, Any]:
    """Process one input set and produce report, workbook, audit and evidence."""
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite previous run: {output_root}")
    output_root.mkdir(parents=True)
    files = _safe_files(input_root)
    classifications: dict[str, int] = {}
    extracted: list[dict[str, Any]] = []
    csv_rows: list[list[Any]] = [["file", "rows", "quantity_total", "revenue_total"]]
    errors: list[dict[str, str]] = []
    for path in files:
        extension = path.suffix.lower()
        kind = {".txt": "text", ".md": "markdown", ".csv": "csv"}.get(extension, "other")
        classifications[kind] = classifications.get(kind, 0) + 1
        data = path.read_bytes()
        item: dict[str, Any] = {
            "name": path.name, "type": kind, "bytes": len(data), "sha256": _sha256(data)
        }
        if kind == "csv":
            try:
                with path.open("r", encoding="utf-8-sig", newline="") as handle:
                    reader = csv.DictReader(handle, strict=True)
                    if reader.fieldnames != ["item", "quantity", "unit_price"]:
                        raise ValueError("unexpected CSV columns")
                    count = 0
                    quantity_total = 0
                    revenue_total = 0.0
                    for row in reader:
                        if None in row or any(value is None for value in row.values()):
                            raise ValueError("inconsistent CSV row width")
                        quantity = int(row["quantity"])
                        price = float(row["unit_price"])
                        if quantity < 0 or price < 0:
                            raise ValueError("negative values are not allowed")
                        count += 1
                        quantity_total += quantity
                        revenue_total += quantity * price
                item.update({"rows": count, "quantity_total": quantity_total,
                             "revenue_total": round(revenue_total, 2)})
                csv_rows.append([path.name, count, quantity_total, round(revenue_total, 2)])
            except (UnicodeError, csv.Error, ValueError) as exc:
                errors.append({"file": path.name, "error": str(exc)})
                item["error"] = str(exc)
        else:
            text = data.decode("utf-8", errors="replace")
            item["characters"] = len(text)
            item["words"] = len(text.split())
        extracted.append(item)
    paragraphs = [
        f"Run ID: {run_id}",
        f"Files discovered: {len(files)}",
        f"Classification: {json.dumps(classifications, sort_keys=True)}",
        f"CSV datasets analyzed: {len(csv_rows) - 1}",
        f"Input errors: {len(errors)}",
        "This report was generated from synthetic or supplied data without executing input files.",
    ]
    _write_docx(output_root / "report.docx", "NEXUS Digital Work Execution Report", paragraphs)
    _write_xlsx(output_root / "analysis.xlsx", csv_rows)
    audit_path = output_root / "audit.jsonl"
    _append_audit(audit_path, "run_started", {"run_id": run_id, "input_count": len(files)})
    _append_audit(audit_path, "inputs_classified", classifications)
    _append_audit(audit_path, "data_extracted", {"files": len(extracted), "errors": len(errors)})
    _append_audit(audit_path, "artifacts_written", {"docx": "report.docx", "xlsx": "analysis.xlsx"})
    evidence = {
        "schema_version": 1, "run_id": run_id, "input_count": len(files),
        "classification": classifications, "extracted": extracted, "errors": errors,
        "artifacts": {
            name: _sha256((output_root / name).read_bytes())
            for name in ("report.docx", "analysis.xlsx", "audit.jsonl")
        },
    }
    (output_root / "evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    validation = validate_run(output_root)
    evidence["independent_validation"] = validation
    (output_root / "evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence


def validate_run(output_root: Path) -> dict[str, Any]:
    """Independently reopen and validate Office packages, audit chain and evidence."""
    required = ("report.docx", "analysis.xlsx", "audit.jsonl", "evidence.json")
    for name in required:
        if not (output_root / name).is_file():
            raise ValueError(f"required artifact missing: {name}")
    with zipfile.ZipFile(output_root / "report.docx") as document:
        if document.testzip() is not None:
            raise ValueError("DOCX ZIP integrity failed")
        xml = _safe_xml_fromstring(document.read("word/document.xml"))
        if not list(xml.iter(f"{{{DOCX_NS}}}p")):
            raise ValueError("DOCX has no paragraphs")
    with zipfile.ZipFile(output_root / "analysis.xlsx") as workbook:
        if workbook.testzip() is not None:
            raise ValueError("XLSX ZIP integrity failed")
        sheet = _safe_xml_fromstring(workbook.read("xl/worksheets/sheet1.xml"))
        rows = list(sheet.iter(f"{{{XLSX_MAIN}}}row"))
        if len(rows) < 1:
            raise ValueError("XLSX has no worksheet rows")
    audit_count = _verify_audit(output_root / "audit.jsonl")
    evidence = json.loads((output_root / "evidence.json").read_text(encoding="utf-8"))
    for name, digest in evidence["artifacts"].items():
        if _sha256((output_root / name).read_bytes()) != digest:
            raise ValueError(f"artifact hash mismatch: {name}")
    return {
        "valid": True, "docx_paragraphs": len(list(xml.iter(f"{{{DOCX_NS}}}p"))),
        "xlsx_rows": len(rows), "audit_events": audit_count,
        "artifacts": list(required),
    }


def run_demo(output_root: Path) -> dict[str, Any]:
    """Run clean 30-file workflow, then repeat against a corrupted CSV copy.

    Both runs are immutable and kept side-by-side so the second run cannot
    overwrite or destroy evidence from the first.
    """
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite demo output: {output_root}")
    output_root.mkdir(parents=True)
    clean_inputs = create_sample_inputs(output_root / "inputs" / "clean")
    clean = execute_run(clean_inputs, output_root / "runs" / "clean", run_id="clean")
    corrupt_inputs = output_root / "inputs" / "corrupted"
    shutil.copytree(clean_inputs, corrupt_inputs)
    (corrupt_inputs / "sales-10.csv").write_text(
        "item,quantity,unit_price\nbroken,not-an-integer\n", encoding="utf-8"
    )
    corrupted = execute_run(corrupt_inputs, output_root / "runs" / "corrupted", run_id="corrupted")
    first_validation = validate_run(output_root / "runs" / "clean")
    second_validation = validate_run(output_root / "runs" / "corrupted")
    result = {
        "sample_files_created": len(_safe_files(clean_inputs)),
        "clean_run": {"input_errors": len(clean["errors"]), "validation": first_validation},
        "corrupted_run": {"input_errors": len(corrupted["errors"]), "validation": second_validation},
        "previous_run_preserved": (output_root / "runs" / "clean" / "report.docx").is_file(),
    }
    (output_root / "demo_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result
