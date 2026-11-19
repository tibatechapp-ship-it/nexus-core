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

**Historical baseline snapshot (`ff120cab`):** Python 3.11 passed its exact-head job, including framework coverage ≥95%, report freshness, and both Novamind test steps; Python 3.12/3.13 were still running at that historical inspection. This is not evidence for the current PR #148 head. Current exact-head validation is tracked in §9 and must be re-run after every source change.

- [x] Python 3.11, 3.12 and 3.13 framework suites pass on the baseline commit.
- [x] 5,342 passed and 30 skipped per Python version.
- [x] Framework coverage 95.02% per version; required floor remains 95%.
- [x] CI and MIZAN workflows pass on the baseline commit.
- [x] Root cause identified: the shared coverage config intentionally omits `src/novamind`; the separate report now uses a dedicated coverage config scoped to that package and no longer suppresses command errors.
- [x] Validate the corrected Novamind test/report commands on the exact current PR head in Python 3.11; the Novamind steps remain explicitly non-blocking and no Novamind coverage threshold is claimed.
- [ ] Confirm the same exact-head result on Python 3.12 and 3.13.
- [ ] Preserve the successful baseline and run all workflows again after each implementation PR.

### Phase 1 — Evidence contract and assurance gate

**Priority: P1.**

Deliverables:
- [x] `src/intelligence/contracts.py`: typed result, finding and evidence records.
- [x] `src/intelligence/contracts.py`: bounded, versioned evidence references, findings, and result contracts.
- [x] `src/intelligence/capture.py`: canonical fixture capture and content-digest verification through an injected immutable evidence sink.
- [x] `src/intelligence/gate.py`: deterministic acceptance rules; missing or unverifiable evidence fails closed.
- [x] PR #148 adds defense-in-depth credential redaction before evidence hashing/persistence; callers remain responsible for sanitized fixtures because this is not complete DLP.
- [ ] Intelligence-specific scope/budget policy adapters remain separate follow-up work; mission authorization remains owned by the existing organization policy.
- [ ] Add the missing `docs/INTELLIGENCE_AND_ASSURANCE.md` design document or remove the stale reference; the roadmap itself and `docs/BEHAVIOR_CAPTURE_AND_REPLAY.md` currently hold the implementation guidance.

Acceptance:
- schema/version validation rejects unknown or malformed fields;
- evidence digests and provenance are verified;
- secrets are redacted before persistence;
- missing evidence cannot become a positive verdict;
- deterministic tests cover malformed input, tampering, oversized payloads and policy denial;
- no new runtime dependency.

### Phase 2 — Behavior Verification Engine

**Priority: P1; first functional engine. Historical implementation snapshot (`ff120cab`):** comparison contract, combined review gate, sanitized-fixture capture, approval-gated rootless replay, explicit completed-mission orchestration, durable audit events, and final-report persistence were implemented; real Rootless Docker E2E passed on that commit. This historical result does not qualify the current PR #148 head; current exact-head checks are tracked in §9.

Deliverables:
- baseline capture for explicitly selected, safe test commands and API/function contracts;
- replay of recorded deterministic inputs against candidate code;
- normalized output comparison with explicit handling for timestamps, random IDs and nondeterministic fields;
- regression report showing matched, changed, missing and inconclusive cases;
- adapter interface so language-specific harnesses remain replaceable.

Implemented first vertical slice:
- [x] src/intelligence/behavior.py: canonical JSON payload digests, immutable baseline/case/observation contracts, evidence verification, and deterministic comparison verdicts.
- [x] src/intelligence/capture.py: bounded recording adapter for already-collected fixtures; applies defense-in-depth credential redaction before hashing and stores content-digested evidence through an injected immutable evidence sink.
- [x] src/intelligence/replay.py: mission-approval-gated adapter that verifies the persisted run_untrusted approval and invokes only the existing rootless container sandbox; process mode is rejected.
- [x] src/intelligence/mission.py: explicit completed-mission orchestration restores the verified final checkpoint, binds the baseline to the mission ID, verifies baseline evidence before candidate execution, stages canonical input fixtures through an argv placeholder, prepares separate disposable workspaces, captures and compares evidence, and appends requested/completed/failed audit events.
- [x] Workspace preparation rejects symlinks and credential-like files, excludes Git metadata and generated/dependency directories, and enforces 100,000-file / 2 GiB limits.
- [x] Tests cover equivalent behavior, output regressions, input drift, missing/not-run cases, unexpected/duplicate cases, invalid evidence, verifier exceptions, capture round trips, sink tampering, approval denial, image mismatch, rootless runner result validation, per-case workspace isolation, cleanup, and audit behavior.
- [x] Comparator and capture adapter perform no execution, subprocess launch, repository import, or network access.
- [x] Historical validation: full mission replay passed against a real rootless Docker daemon and preloaded digest-pinned runner image (`Rootless behavior replay E2E` run `44533579702` on `ff120cab`).
- [ ] Revalidate the full flow on the current PR #148 head after every source change; historical E2E runs do not satisfy the current-head gate. Replay remains explicit, never automatic.
- [x] Combine the evidence AssuranceDecision and BehaviorComparison through a deterministic review gate; only both assured + equivalent yield an assured result.
- [x] Persist release `branch`, `patch_path`, `report_path`, and ticket ID on the mission record before marking the release task complete; reject incomplete release metadata and retain fields through the terminal mission transition.
- [x] Append the explicit behavior replay verdict, baseline/candidate revisions, case outcomes, and evidence IDs to the mission `REPORT.md` atomically; audit report persistence and mark legacy missions without a report path as unavailable.
- [x] Persist a combined evidence-assurance + behavior-comparison verdict in the mission replay result, final report, and completion audit event. The combined gate remains review-only and grants no execution/release authority.
- [ ] Connect Coder Engine / organization QA quality results and their persisted evidence into the same mission-level assurance contract.

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

Each phase is a separate reviewable PR with a narrow scope. The earlier PR #141 scope note is historical and does not describe the current execution stack: PR #148 is the security/replay-hardening follow-up stacked on PR #147, while Coder Engine / organization integration remains a later gated workstream.

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


## 9. PR 148 hardening follow-up and execution control

**Follow-up branch:** fix/pr147-evidence-redaction  
**Target:** feat/intelligence-evidence-contract (the implementation branch behind PR 147).  
**Policy:** keep this follow-up Draft until all required checks pass on one exact head SHA. A passing CI run on an earlier SHA is historical evidence only.

### Additional controls delivered in the follow-up

- [x] Redact common credential-bearing keys and recognizable bearer, assignment, provider-token, cloud-key and private-key patterns before calculating payload digests or persisting evidence.
- [x] Stamp captured artifacts with nexus.secret-redaction/v1; document that this is defense in depth, not complete DLP.
- [x] Require one-to-one evidence-reference mapping for baseline cases and candidate observations; reject orphaned, duplicate and reused references.
- [x] Reject credential-bearing directories (.aws, .ssh, .azure, .gcloud, .kube, .gnupg, .docker) and additional key-store suffixes during replay snapshot preparation.
- [x] Compare requested replay case IDs and canonical input digests with the trusted baseline before checkpoint restore or candidate execution; apply the same sanitizer before hashing and before staging fixtures into disposable workspaces.
- [x] Add negative-path tests for the above controls, including proof that secret-like fixture values do not reach the staged replay input.
- [x] Apply the same credential sanitizer to evidence-sink and rootless-runner exception details before they can enter replay failure audit records; add a regression test proving a provider-token-shaped value is not persisted.
- [x] Restore a genuine two-case workspace-isolation test: two cases must receive two distinct disposable workspaces copied from the same verified checkpoint.
- [ ] Run the complete Python 3.11/3.12/3.13 matrix, exact 95% framework coverage gate, report freshness, MIZAN and all security checks on the same final PR head.
- [ ] Run the real Rootless Docker E2E on that same final PR head.
- [ ] Obtain independent review; no review submissions or inline review threads were present on PR #147 at the last inspection.

### Current execution order — authoritative

The phase descriptions above define the destination; this ordered queue defines what may be executed next. Do not run workstreams in parallel when one changes the contracts consumed by another.

1. **Freeze the current implementation scope and record the exact head SHA.** While required workflows are running, do not push unrelated changes. A necessary fix creates a new head and invalidates every earlier exact-head result.
2. **Close G0 on one SHA.** Require completed CI, the complete Python 3.11/3.12/3.13 test matrix, the independent ≥95% framework coverage gate, report freshness, security checks, and real Rootless Docker E2E. Queued, pending, skipped-required, cancelled, or stale-SHA jobs are not passes.
3. **Close G1 — evidence safety.** Verify sanitizer behavior for structured fields and free text, exception paths, sink failures, canonicalization, payload limits, immutable evidence IDs, digest verification, and exact one-to-one evidence mapping. Treat redaction as defense in depth, never as permission to ingest real secrets.
4. **Close G2 — replay safety.** Verify approval provenance, digest-pinned image enforcement, rootless-only execution, preflight-before-restore, snapshot exclusions, per-case workspace isolation, bounded execution, cleanup, and failure auditing. Any process fallback or credential-bearing workspace blocks progression.
5. **Close G3 — assurance correctness.** Verify that incomplete, missing, stale, altered, or unverifiable evidence can never yield an assured result; verify the combined behavior + evidence gate and report/audit persistence fail closed. Obtain independent review of the security-sensitive changes.
6. **Only then start G4 — Coder Engine/quality-gate adapter.** Keep it narrow: translate existing validated RepairPlan and QA outputs into typed evidence. Preserve policy, approvals, isolated worktree, and current quality gate; do not add a parallel repair engine.
7. **G5 — qualify a small critical agent cohort.** Build a labelled task corpus and score agents by real task outcomes, correctness, regressions, cost, latency, reliability, and evidence quality. Inventory/import success is not qualification.
8. **G6 — expand capabilities and operations.** Add bounded read-only reverse-engineering adapters, then unify security/MIZAN evidence, then controlled MCP, dashboards, SLOs, recovery drills, cost controls, and release rollback. Do not reverse this order.

**Current checkpoint (2026-11-19):** PR #148 head `e781d1926dbc61799000327c55163be5c6f97cf5`; Rootless Docker E2E succeeded on that SHA; the Python 3.11/3.12/3.13 framework test jobs were still running at the last live inspection; CI run was pending with no jobs exposed yet. G0 is therefore open. PR #148 and PR #147 remain Draft; no merge/release/deploy is authorized.

### Revised delivery gates

| Gate | Required proof | Stop condition |
|---|---|---|
| G0 — Exact-head integrity | PR head SHA recorded; CI, test matrix and E2E all refer to that SHA | Any check is missing, stale or still running |
| G1 — Evidence safety | Secret redaction tests, immutable sink digest checks, one-to-one evidence mapping, malformed/oversized input tests | Any secret-bearing fixture is persisted or evidence mapping is ambiguous |
| G2 — Replay safety | Exact baseline case/input preflight, persisted human approval, digest-pinned image, rootless isolation, per-case workspace separation, cleanup | Any preflight occurs after restore/execution, or any host-process fallback exists |
| G3 — Assurance correctness | Evidence verification, explicit partial/invalid states, behavior comparison, independent assurance and combined gate | Missing evidence can produce an assured result |
| G4 — Integration | Coder Engine/QA evidence enters the mission contract through existing RepairPlan and quality gates | Parallel repair path or gate bypass appears |
| G5 — Fleet qualification | Per-agent evidence matrix; synthetic vs real task harness separated; task quality, cost, latency and reliability recorded | Inventory/import health is presented as task competence |
| G6 — Product and operations | Observability, durable recovery, cost budgets, release rollback, operator UX and incident drills | UI or automation hides uncertainty or bypasses human approvals |

### Professional implementation sequence

1. **Close G0–G3 first.** Do not begin a broad feature expansion while the evidence/replay foundation is still changing.
2. **Integrate existing quality systems.** Adapt existing Coder Engine, MIZAN, src/security, observability and durable-workflow results to the shared contract; do not duplicate scanners, queues or policy engines.
3. **Build a representative task corpus.** Start with a small critical agent cohort and labelled repositories/tasks. Record exact model/provider, prompt/template, tool policy, dataset revision, environment, cost and latency for every run.
4. **Qualify agents individually.** Keep discovery, importability, construction, synthetic invocation, task validation and production qualification as separate maturity levels. Unknown evidence remains unknown.
5. **Add read-only reverse-engineering adapters incrementally.** Bound archive expansion, file count, recursion, parser time and memory; no execution or network by default.
6. **Unify security assessment after adapters are stable.** Keep heuristic signals distinct from confirmed findings; require authorization for active validation and retest.
7. **Expose MCP/UI last.** Every surface consumes the same contracts and gates; no UI-side alternate execution path.
8. **Operationalize only after measurable gates.** Add SLOs for workflow completion, evidence integrity, recovery, false positives, cost per successful task and rollback time.

### Evidence discipline

- A run is current only if its commit SHA equals the current PR head SHA.
- A green CI job does not imply the non-blocking NovaMind suite or its coverage is production-qualified.
- A rootless E2E pass proves the tested container path and scenarios only; it does not prove all mission integrations safe.
- The 106 inventory records remain inventory records, not 106 task-validated agents.
- Benchmark claims require a versioned dataset, pinned environment, repeated runs and raw machine-readable results.
- PR approval, merge, release and deployment remain separate human-controlled decisions.


### G4 implementation contract — Coder Engine and quality gate

The current Coder Engine and quality-gate APIs are useful producers of execution outcomes, but they are not yet durable evidence authorities:

- Coder Engine defaults to process execution for trusted local development. That mode must never be promoted into an untrusted mission assurance result.
- Quality-gate and engine JSONL writes are best-effort today; a failed log write does not necessarily fail the engine.
- A returned ok=true is an orchestration summary, not proof that every command ran in the intended isolated environment or that the result is reproducible.

Therefore the integration adapter must:

1. Require container execution, explicit feature enablement, persisted human approval and an immutable digest-pinned image for untrusted candidate validation. Reject process mode at the assurance boundary even if the Coder Engine supports it for trusted local development.
2. Bind every result to mission_id, run_id, candidate Git SHA, baseline SHA, RepairPlan digest, test/gate configuration digest, runner image digest, Python/toolchain versions and timestamps.
3. Convert each test, static-analysis, security and independent-review outcome into a separate typed evidence artifact. Store it through the immutable evidence sink; verify the returned digest and provenance independently.
4. Redact output before persistence. Do not treat raw stdout/stderr, exception messages, patch contents or model explanations as safe evidence by default.
5. Fail closed if evidence persistence, digest verification, report writing or audit append fails. Keep best-effort operational logs separate from mandatory assurance evidence.
6. Preserve the existing RepairPlan validation, isolated worktree, policy decision, reviewer/council requirements and human approval. The assurance gate may reject or request human review; it must not execute a repair, approve a merge or authorize a deployment.
7. Test negative paths: process-mode attempt, missing approval, image digest mismatch, evidence-sink outage, altered artifact, missing gate result, stale candidate SHA, truncated output, timeout, failed cleanup and audit/report persistence failure.

The adapter should be a narrow boundary module with contract tests; do not rewrite Coder Engine or replace the existing quality gate to accomplish this integration.
