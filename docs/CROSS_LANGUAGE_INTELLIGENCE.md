# Cross-language defect intelligence

## Purpose

The coding engine previously retrieved source context across several languages,
but its deterministic defect-discovery pass inspected Python files only. This
slice closes that mismatch: the read-only static pass now scans supported
source extensions and reports portable, evidence-backed findings with a
repository-relative path, line number, stable rule ID, severity and source.

## Supported source families

Python, Python stubs, JavaScript, JSX, MJS, CJS, TypeScript, TSX, Go, Rust,
Java, Kotlin, PHP, Ruby, C#, Swift, Dart, Vue and SQL.

Python files additionally receive an AST syntax check. Other languages are
not parsed for syntax validity by this component; the scanner does not claim
compiler-grade understanding.

## Rules in this version

| Rule ID | Signal | Default severity |
| --- | --- | --- |
| python-syntax | Python parse error | high |
| silent-exception | `except Exception: pass` | low |
| todo / fixme / xxx | Unresolved work markers | low |
| tls-verification-disabled | Common disabled TLS verification flags | high |
| dynamic-evaluation | `eval(...)` or `new Function(...)` | medium |
| shell-execution | `shell=True` or direct Node `child_process.exec(...)` | medium |
| hardcoded-credential | Credential-like assignment to a string literal | medium |

Credential findings redact values: source snippets and matched values are never
included in the finding payload.

## Safety and limits

- Read-only: repository source is parsed/read as data; no repository code is
  imported, built, tested or executed by this scanner.
- Bounded: 200 findings by default, 512 KiB per file, deterministic path order.
- Skips symlinks, hidden paths, common generated/dependency directories and
  paths named for secrets, credentials or private material.
- Line-oriented rules are conservative heuristics. They can produce false
  positives and false negatives; they are triage evidence, not proof of exploitability.
- This component does not replace MIZAN, language-native linters, CodeQL,
  dependency auditing, the coding engine's isolated test gate or an independent
  human review.
- The model may rank and add findings, but deterministic findings are retained
  if the model provider fails. Model output is not treated as trusted evidence.

## Local verification

```bash
python -m pytest tests/test_coder_detector.py tests/test_coder_detector_multilang.py -q
```

The portfolio validation phase should run this scanner against real project
checkouts in read-only mode, record per-project language and rule coverage,
then create separately approved repair tasks. A clean scan is not a claim that
a repository is defect-free.
