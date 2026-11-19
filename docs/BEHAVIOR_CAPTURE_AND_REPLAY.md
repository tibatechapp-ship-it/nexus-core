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
- runs as container UID 0 only inside the rootless user namespace. Container UID 0
  maps to the unprivileged host account running the rootless daemon; it is not host
  root. This preserves private owner-only mission worktrees while retaining dropped
  capabilities and no-new-privileges;
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

For the mission lifecycle adapter, each `BehaviorCaseSpec` must contain exactly
one `{behavior_input}` argv token. The mission adapter replaces it with the in-container path
`/workspace/.nexus-behavior/input.json` and stages the canonical JSON fixture
inside that case's disposable workspace. This avoids shell interpolation and
makes the exact input payload available to the declared command without stdin
ambiguity. The fixture is limited to 1 MiB and receives owner-only permissions.
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

## Runtime cleanup and validation status

The real Rootless Docker E2E workflow has verified approval-bound execution,
network isolation, and a read-only container root with a preloaded digest-pinned
image. The mission adapter persists the behavior verdict and evidence IDs into
the final mission report and organization audit log.

The Docker client now receives a private per-invocation `--cidfile`. If the
client-side wait reaches its deadline, the adapter kills the local Docker CLI
process group and then attempts `docker rm --force <container-id>` with a
separate 10-second cleanup deadline. The result records whether cleanup was
attempted, confirmed, or left unconfirmed; an unconfirmed cleanup remains a
failed replay and is never treated as a successful run. No resource limits or
isolation controls are relaxed to make cleanup succeed.

The cleanup path is covered by unit tests for confirmed removal, failed removal,
and a missing/malformed container ID. The dedicated Rootless Docker workflow
continues to validate the real daemon path. No automatic replay is wired into
arbitrary missions.


## Mission lifecycle adapter

Use `run_mission_behavior_replay` only as an explicit operator-requested action
after the mission reaches `done`. The orchestrator now persists a final
pre-completion checkpoint after the release wave and before cleaning its live
worktree. The replay service requires a baseline whose target is exactly
`mission:<mission_id>`, restores that latest verified checkpoint, and confirms
its phase matches the completed mission and that it is the final running state.
It rejects a missing, stale, or invalid checkpoint. It creates one temporary copy
per case, removes Git metadata and common generated/dependency directories, rejects
symlinks and credential-like files, and enforces file-count and total-size limits.
Temporary workspaces are deleted on success or failure. Requested and terminal
outcomes are appended to the organization audit log; evidence bytes are stored
through the injected immutable evidence sink.

The copied workspace retains owner-only permissions. The rootless container's
namespace root maps to the host account that owns the workspace, so the sandbox
can read and write the disposable copy without making source files world-readable.
The original mission checkpoint is never mounted writable.
