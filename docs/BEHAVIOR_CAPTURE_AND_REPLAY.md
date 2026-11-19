# Behavior Capture and Replay

## Purpose

The behavior layer has three deliberately separate responsibilities:

1. `capture.py` records already-collected, sanitized input/output fixtures as bounded evidence.
2. `replay.py` executes explicitly declared test commands only after checking a persisted mission approval and delegates to the existing rootless container sandbox.
3. `behavior.py` compares the resulting evidence-backed observations with a baseline. It never executes code.

No verdict from these modules authorizes a merge, release, or deployment.

## Recording an existing baseline

A caller supplies successful, already-collected fixtures and an immutable evidence sink:

```python
baseline = capture_baseline(
    target="repo:example",
    revision="git-sha",
    run_id="baseline-001",
    cases=[
        CapturedCase(
            case_id="public-api-health",
            input_payload={"path": "/health"},
            output_payload={"status": 200, "body": {"ok": True}},
        ),
    ],
    collected_by="approved-test-harness",
    sink=evidence_sink,
)
```

The sink must persist bytes immutably by evidence ID and return an `EvidenceReference`
whose SHA-256 is the digest of the exact stored bytes. The adapter verifies the returned
ID, kind, collector, and digest. Artifacts are canonical JSON and limited to 1 MiB.

Only sanitized test fixtures may be persisted. Do not record credentials, tokens,
private keys, personal data, or unrestricted production payloads. The adapter cannot
infer whether arbitrary user-supplied fixture content is sensitive.

## Executing candidate cases

`execute_authorized_cases` is the only execution-facing adapter in this layer. It:

- accepts container mode only; trusted-local process mode is rejected;
- requires container enablement and an immutable lowercase SHA-256 image reference;
- retrieves the mission's persisted approval by ID and verifies kind
  `run_untrusted`, approved status, a non-empty human decision-maker, and exact image subject;
- requires a separate existing disposable workspace for each case;
- passes argv directly (never through a host shell) to `run_in_container`;
- requires the existing rootless Docker preflight, network isolation, read-only image
  filesystem, dropped capabilities, no-new-privileges, and bounded resources;
- treats timeout, output truncation, nonzero exit, and malformed runner results as failure;
- never falls back to `subprocess`, the legacy process sandbox, or an unapproved runner.

Example shape:

```python
cases = [
    ReplayCommandCase(
        case_id="public-api-health",
        argv=("python", "-m", "pytest", "-q", "tests/test_health.py"),
        workspace=disposable_workspace,
        input_payload={"path": "/health"},
    ),
]
captured = execute_authorized_cases(
    mission_id=mission.id,
    execution_policy=mission.execution_policy,
    approval_store=org_store,
    cases=cases,
)
observations, evidence = capture_observations(
    target="repo:example",
    revision=candidate_sha,
    run_id="candidate-001",
    cases=captured,
    collected_by="nexus-rootless-replay",
    sink=evidence_sink,
)
```

The caller must stage the sanitized fixture in the case workspace and make the
declared command consume that fixture. `input_payload` is the canonical evidence
representation and digest source; it is not implicitly sent to the process as stdin.
Each case workspace must be independently prepared from the same candidate snapshot,
not reused after another case has executed.

## Comparison and decision

Call `compare_behavior` with the trusted baseline, candidate observations, candidate
evidence references, and a verifier that independently retrieves and checks stored
evidence. Then combine its result with `evaluate_assurance` using
`evaluate_behavior_gate`.

- `assured`: all evidence is verified and all recorded cases match.
- `needs_human`: evidence or execution is partial/incomplete.
- `rejected`: evidence is invalid, a case regressed, or policy validation failed.

The comparator only proves agreement over the recorded test corpus. It does not
prove equivalence for unobserved inputs.

## Remaining integration

The adapter is implemented and independently testable. The remaining integration
work is to construct per-case disposable workspaces from a mission snapshot, connect
the adapter to the orchestrator's mission lifecycle and durable audit records, and
run the complete workflow against a controlled fixture repository. No automatic
replay is wired into arbitrary missions yet.
