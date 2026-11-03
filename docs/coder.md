# The self-coding engine (src/coder) + independent quality gate (src/quality_gate)

> محرك البرمجة ذاتي الحركة وبوابة الجودة المستقلة — المرحلتان الثانية والثالثة
> من خطة الـ90 يوماً: تحليل → اكتشاف → مخطط معلن → تنفيذ معزول → بوابة مستقلة.

## The five-stage loop

`src/coder/engine.py::run_engine(goal, connector, ...)` orchestrates one
iteration cycle over the platform's own primitives — no parallel paths:

| Stage | Module | What it does |
|---|---|---|
| 1. Analyze | `analyzer.py` | AST module map (path, docstring, imports, LOC) — no regex-on-source |
| 2. Detect | `detector.py` | Deterministic static pass (syntax errors, smell markers) + model-ranked defects via any BYOK connector |
| 3. Plan | `plan.py` | The model MUST emit a `RepairPlan` JSON object; `validate()` rejects incomplete/unsafe plans before any mutation |
| 4. Execute | `sandbox.py` | File mutations stay inside a throwaway workdir; tests run in an rlimits-boxed subprocess (Termux-safe, no `RLIMIT_AS`) |
| 5. Gate | `src/quality_gate/runner.py` | Separate-process gates (pytest → compileall → annotations), verdict + JSONL report |

Hard rules enforced by the code, not by convention:

- **No plan, no edit** — the engine never writes a file that was not declared
  by a validated `RepairPlan` (G2).
- **High risk needs a council** — any step with `risk: "high"` is auto-rejected
  unless a `council` callable approves it (M2.5 acceptance).
- **The engine reports, never crashes** — every failure mode returns
  `{"ok": False, ...}` with an `attempts` audit trail; nothing escapes.
- **Trace everything** — each stage writes to the platform's standard trace log
  (`src/observability/trace.py`, fields `ts/agent/tool/duration_ms/outcome`).

## Plan schema (`RepairPlan`)

```python
RepairPlan(goal, defects, steps, tests_to_run, rollback)
Step(file, action, reason, patch_hint, risk)   # action: edit|create|delete
```

`validate()` rejects: missing goal / steps / tests, bad action or risk level,
absolute or escaping paths, missing `patch_hint` on edit/create, missing
`reason`. JSON round-trips via `to_json()` / `plan_from_json()` (garbage-tolerant).

## The independent gate

`run_gate(workdir, gates=None)` runs each command in its own subprocess and
returns `(ok, results)`; every run appends a full report line to
`runs/quality_gate.jsonl` (or `NEXUS_QUALITY_GATE_LOG`). The gate shares no
state with the engine — the evaluator is never a party to the evaluated.

## Failover-aware model access

The engine talks to the model through the connector family merged in
`feat(connectors)` (M1.3/M1.4): `glm-local` (self-hosted vLLM), `glm-cloud`
(Z.AI fallback) and `glm` (local-first failover). Any BYOK object exposing
`async generate(prompt, system_prompt)` works, which keeps the whole engine
testable offline with scripted connectors.

## Running it

```bash
# hermetic end-to-end demo (scripted connector, no network, exit 0 = green gate)
python3 scripts/coder_demo.py
```

Tests: `tests/test_coder_{plan,analyzer,sandbox,detector,engine}.py` +
`tests/test_quality_gate.py` — 76 hermetic cases, 100% branch coverage of the
new surface, no external network anywhere.
