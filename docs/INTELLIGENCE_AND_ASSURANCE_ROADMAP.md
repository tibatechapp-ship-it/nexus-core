# Intelligence & Assurance Roadmap

> Status: approved engineering direction; implementation is staged behind the existing quality and security gates.
> Baseline: `4061564f62aeaea7539010c9bf6b2642b1cc2c69` (2026-11-19).
> This roadmap extends, rather than replaces, the existing `V2_ROADMAP.md`, `CROSS_LANGUAGE_INTELLIGENCE.md`, `SECURITY.md`, MIZAN roadmap, Coder Engine, and organization execution policy.

## 1. Product outcome

NEXUS CORE should be able to understand an authorized software system, identify and substantiate risks, propose a bounded repair, and demonstrate that the repair preserves required behavior.

The capability is an assurance workflow, not three autonomous writers:

1. **Reverse Engineering** builds a read-only, evidence-linked map of an authorized application or repository.
2. **Security Assessment** combines existing deterministic scanners and policy-aware analysis to identify and validate findings within an explicit scope.
3. **Behavior Verification** records or defines observable contracts and compares baseline behavior with candidate behavior after a change.
4. **Evidence & Assurance Gate** evaluates provenance, reproducibility, coverage, risk, policy compliance, and independent review.
5. Only a passing, authorized repair is translated into a validated `RepairPlan` and sent through the existing Coder Engine / mission Worktree flow.

No new engine may bypass `ExecutiveOrchestrator`, execution policy, `RepairPlan`, the isolated quality gate, audit records, or human approval for merge/deploy.

## 2. Existing capabilities to reuse

Do not create parallel implementations where the repository already has a maintained capability.

| Existing capability | Reuse in this roadmap |
|---|---|
| `src/coder/analyzer.py`, `context.py`, `detector.py` | Read-only repository understanding, language detection, bounded source context |
| `src/coder/engine.py`, `plan.py`, `sandbox.py`, `container_sandbox.py` | Validated edits and isolated execution; sole repair path |
| `src/security/` | Deterministic offline security rules, classification, scoring, reports |
| MIZAN | Independent read-only static-analysis evidence and report freshness |
| `src/mcp/` | Controlled tool integration; explicit allowlists and validated schemas |
| `src/observability/`, `src/durable/` | Trace provenance, checkpoints, audit and resume |
| `src/org/` | Mission policy, approvals, operator identity, execution boundaries |
| `src/verify/`, `src/quality_gate/`, existing tests | Existing verification and release gates |

The current security scanner is heuristic/static analysis, not proof of exploitability. Findings must retain that distinction.

## 3. Target architecture

```text
Mission / ExecutiveOrchestrator
  └── Scope + authorization + budget + execution policy
       ├── Reverse Engineering (read-only adapters)
       ├── Security Assessment (MIZAN + src/security + scoped checks)
       └── Behavior Verification (baseline / replay / comparison)
                |
                v
       Evidence & Assurance Contract
                |
       Independent Review + Quality Gate
                |
        accept / reject / needs-human
                |
        Coder Engine -> RepairPlan -> Mission Worktree
                |
        tests + security retest + behavior comparison
                |
        audited result; human approval before merge/deploy
```

### Shared result contract

Every engine returns a typed, versioned result with:

- mission and run identifiers;
- engine name and contract version;
- target identity and authorized scope;
- status: `complete`, `partial`, `rejected`, or `failed`;
- findings with stable rule IDs, severity, confidence and rationale;
- evidence references with content digests, source locations and collection method;
- limitations, skipped inputs and coverage gaps;
- reproducibility instructions and tool/version metadata;
- policy decisions and required human actions.

Evidence records must not embed secrets, private keys, tokens, or unrestricted source dumps. Redaction happens before persistence and reporting. A model-generated explanation is not evidence by itself.

## 4. Workstreams and phases

### Phase 0 — Baseline and quality closure

**Status: baseline passed; Novamind measurement corrected, awaiting exact-head validation.**

- [x] Python 3.11, 3.12 and 3.13 framework suites pass on the baseline commit.
- [x] 5,342 passed and 30 skipped per Python version.
- [x] Framework coverage 95.02% per version; required floor remains 95%.
- [x] CI and MIZAN workflows pass on the baseline commit.
- [x] Root cause identified: the shared coverage config intentionally omits `src/novamind`; the separate report now uses a dedicated coverage config scoped to that package and no longer suppresses command errors.
- [ ] Validate the corrected Novamind report on the exact current PR head; keep it explicitly non-blocking until a separately approved coverage threshold exists.
- [ ] Preserve the successful baseline and run all workflows again after each implementation PR.

### Phase 1 — Evidence contract and assurance gate

**Priority: P1.**

Deliverables:
- [x] `src/intelligence/contracts.py`: typed result, finding and evidence records.
- `src/intelligence/evidence.py`: digest, provenance, redaction and bounded evidence references.
- `src/intelligence/policy.py`: scope, permission and budget checks that defer to the existing mission policy.
- [x] `src/intelligence/gate.py`: deterministic acceptance rules; missing or unverifiable evidence fails closed.
- `docs/INTELLIGENCE_AND_ASSURANCE.md`: contract, threat model, data lifecycle and examples.

Acceptance:
- schema/version validation rejects unknown or malformed fields;
- evidence digests and provenance are verified;
- secrets are redacted before persistence;
- missing evidence cannot become a positive verdict;
- deterministic tests cover malformed input, tampering, oversized payloads and policy denial;
- no new runtime dependency.

### Phase 2 — Behavior Verification Engine

**Priority: P1; first functional engine. Status: comparison contract, combined review gate, and safe fixture-capture adapter implemented; approved execution/replay integration remains open.**

Deliverables:
- baseline capture for explicitly selected, safe test commands and API/function contracts;
- replay of recorded deterministic inputs against candidate code;
- normalized output comparison with explicit handling for timestamps, random IDs and nondeterministic fields;
- regression report showing matched, changed, missing and inconclusive cases;
- adapter interface so language-specific harnesses remain replaceable.

Implemented first vertical slice:
- [x] src/intelligence/behavior.py: canonical JSON payload digests, immutable baseline/case/observation contracts, evidence verification, and deterministic comparison verdicts.
- [x] src/intelligence/capture.py: bounded recording adapter for already-collected, sanitized fixtures; stores content-digested evidence through an injected immutable evidence sink.
- [x] Tests cover equivalent behavior, output regressions, input drift, missing/not-run cases, unexpected/duplicate cases, invalid evidence, verifier exceptions, capture round trips, sink tampering, and size limits.
- [x] Comparator and capture adapter perform no execution, subprocess launch, repository import, or network access.
- [ ] Add an execution adapter that obtains mission authorization and invokes only the existing approved rootless-container runner; no legacy process runner.
- [x] Combine the evidence AssuranceDecision and BehaviorComparison through a deterministic review gate; only both assured + equivalent yield an assured result.
- [ ] Connect baseline/candidate evidence to Coder Engine quality results and mission audit records.

Safety:
- never execute repository code during static analysis;
- runtime replay occurs only in the existing isolated sandbox/container policy;
- test commands, environment, network and resource limits are explicit;
- recorded fixtures are treated as untrusted input and size-bounded.

Acceptance:
- identical implementation produces stable replay results;
- intentional behavior changes are reported, not silently normalized away;
- timeouts, crashes, output truncation and missing baseline data produce inconclusive/failing gates;
- tests cover determinism, flaky cases, path isolation and hostile fixtures;
- behavior gate integrates with Coder Engine quality results without bypassing RepairPlan.

### Phase 3 — Reverse Engineering Engine

**Priority: P2.**

Build on the existing competitive reverse-engineering and cross-language intelligence work. Study REA as an external reference; do not copy its source or import its dependencies without license and supply-chain review.

Initial adapters:
1. repository and filesystem structure;
2. JavaScript/TypeScript and Electron metadata;
3. Android APK metadata and manifest/resource inventory;
4. .NET assembly metadata;
5. binary metadata and strings as inert data.

Later adapters may integrate Ghidra, JADX or other specialist tools through isolated, opt-in adapters. They are not core runtime dependencies.

Acceptance:
- static/read-only by default;
- supported formats and parser limitations are explicit;
- input size, archive expansion, recursion and time are bounded;
- no auto-execution, dynamic loading or network access;
- findings cite file offsets, symbols, paths or other reproducible source locations;
- unsupported and malformed formats return partial results with limitations, not fabricated certainty.

### Phase 4 — Security Assessment Engine

**Priority: P2; reuse before expansion.**

Unify the evidence and reporting surface of `src/security/`, MIZAN, and existing Coder Engine checks. Do not duplicate their scanners.

Capabilities:
- asset and scope inventory;
- deterministic static checks and dependency/configuration review;
- deduplication with rule identity and source provenance;
- severity and confidence kept as separate dimensions;
- retest of findings against the candidate revision;
- remediation plans routed through Coder Engine only after authorization.

ARTEX is a design reference for scoped evidence collection and approval workflows, not a source-code dependency. Its AGPL-3.0 licensing requires legal review before any code reuse.

Acceptance:
- no tests against third-party targets without explicit authorization;
- no exploit or destructive validation by default;
- active checks require explicit scope, approval, rate limits and isolated execution;
- every confirmed finding has reproducible evidence; heuristic signals remain labelled as candidates;
- retest can mark fixed, still present, regressed or inconclusive.

### Phase 5 — Controlled MCP/tool adapters

**Priority: P3.**

Expose selected read-only analysis tools through the existing MCP layer:
- inspect repository;
- list detected components and languages;
- retrieve bounded evidence;
- request a scoped security assessment;
- compare baseline and candidate behavior.

Every tool must have a strict schema, explicit allowlist, bounded output, idempotency where applicable, audit events and permission checks. Write/execute tools remain outside the read-only adapter set and use the established approval path.

### Phase 6 — Evaluation, operations and product surface

**Priority: P3.**

- golden corpus of small, medium and adversarial repositories;
- language/format coverage report;
- precision/recall measurements on labelled findings where a defensible corpus exists;
- behavior-replay stability and false-change metrics;
- cost, latency, memory and tool-call budgets;
- dashboard views for evidence, limitations, approvals and retest status;
- Arabic-first reports with machine-readable JSON output.

No performance, accuracy or model-quality claims without a reproducible benchmark.

## 5. Delivery sequence

1. Close the Novamind coverage-reporting ambiguity.
2. Implement and test the evidence contract and assurance gate.
3. Implement Behavior Verification as the first end-to-end vertical slice.
4. Integrate existing Coder Engine and test-gate outputs.
5. Add Reverse Engineering read-only adapters in small increments.
6. Unify existing security/MIZAN findings under the shared evidence contract.
7. Add MCP exposure only after tool contracts and authorization tests pass.
8. Publish evaluation results and then consider UI work.

Each phase is a separate reviewable PR with a narrow scope. The current PR #141 remains focused on the Coder Engine / organization integration; this roadmap is developed on a separate branch.

## 6. Global non-negotiable gates

- Framework coverage never below 95% on Python 3.11, 3.12 and 3.13.
- New modules target at least 95% coverage; security-critical policy and evidence branches require explicit negative-path tests.
- CI, MIZAN, tests, lint, typing and report-freshness checks pass on the exact candidate SHA.
- No new runtime dependency without an ADR and a demonstrated need.
- No execution of untrusted code during static analysis.
- No process-mode execution of untrusted code; container execution requires the existing explicit approval and digest-pinned image policy.
- Read-only by default; scope and budget are mandatory for active checks.
- No unsupported claim of exploitability, complete coverage or behavior equivalence.
- No merge, release or deployment without explicit human approval.

## 7. External project notes

- **REA**: inspect architecture and adapter boundaries; independently validate license, dependencies and security before optional integration.
- **ARTEX**: learn from scope, evidence and approval concepts; AGPL-3.0 means no code copying or linking until license obligations are reviewed.
- **rust-anything**: use behavior-preserving replay as a design pattern; do not introduce a Rust rewrite project until profiling identifies a bottleneck and compatibility tests exist.
- **Model announcements**: new models enter the council only through the existing reproducible task suite, cost accounting and provider policy.

## 8. Definition of done

The initiative is complete only when a scoped mission can:
1. map an authorized target without executing it;
2. produce evidence-backed, limitation-aware findings;
3. capture and replay required baseline behavior in an approved sandbox;
4. propose a bounded RepairPlan;
5. pass independent review, tests, security retest and behavior comparison;
6. produce an auditable report with reproducible evidence;
7. stop safely on missing authorization, incomplete evidence or failed gates.

A clean scan is not proof that a system is defect-free. A passing replay is not proof of equivalence outside the recorded corpus.
