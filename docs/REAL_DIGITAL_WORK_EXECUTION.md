# ROUND 5 — Real Digital Work Execution

This module is a reproducible proof that NEXUS can perform a bounded non-code
workflow and produce independently verifiable files. It uses only the Python
standard library and never executes input files.

## Run the complete proof

From the repository root:

\`\`\`bash
python -m src.digital_work.cli demo --output .nexus-digital-work-proof
\`\`\`

The command creates exactly 30 synthetic inputs (10 TXT, 10 Markdown, 10 CSV),
classifies and extracts metadata, analyzes numeric CSV columns, and writes:

- \`runs/clean/report.docx\`: a genuine Office Open XML Word document.
- \`runs/clean/analysis.xlsx\`: a genuine Office Open XML Excel workbook.
- \`runs/clean/audit.jsonl\`: append-only SHA-256 chained events.
- \`runs/clean/evidence.json\`: input hashes, classifications, extraction outcomes,
  artifact hashes and independent validation result.
- \`runs/corrupted/*\`: a second run after one CSV is deliberately malformed.
- \`demo_result.json\`: proof summary for both runs.

The clean run must have zero input errors. The corrupted run must record the
malformed CSV as an error without aborting unrelated work. The clean run's
artifacts remain in their original directory and are validated again after
the corrupted run.

## Independent validation

\`\`\`bash
python -m src.digital_work.cli validate .nexus-digital-work-proof/runs/clean
python -m src.digital_work.cli validate .nexus-digital-work-proof/runs/corrupted
pytest -q tests/test_digital_work.py
\`\`\`

Validation reopens both Office ZIP packages, parses their XML, verifies the
audit hash chain, and recomputes every recorded artifact hash. It is not a
claim of Microsoft Office application compatibility testing.

## Safety and limits

- Input files are data only; no scripts, macros, formulas, or embedded content
  are executed.
- Symlinks, paths escaping the input root, secret-like filenames, and files
  larger than 1 MB are rejected.
- Outputs are immutable per run: an existing output directory is never replaced.
- The demo uses synthetic data. It does not connect to email, cloud drives,
  browsers, desktop applications, Android, or external services.
- This is the first digital-work execution proof, not yet general-purpose
  computer use or a production document automation service.
