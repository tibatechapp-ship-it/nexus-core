# MIZAN security confirmation contract

## Current safety behavior

The static scanner may report a suspicious source pattern, but a pattern match is
not proof that the application reaches a vulnerable operation or that an
attacker-controlled value can influence it.

The previous generic probes were self-confirming: they assembled a payload
containing the expected marker and then searched their own generated output for
that marker. They did not execute the target application's real data/control
flow. Their `confirmed` results were therefore not valid vulnerability
evidence.

Until a target-aware verifier is implemented and reviewed:

- `confirm()` returns `inconclusive` for every finding.
- It does not invoke the supplied sandbox.
- `probe_for()` raises `NotImplementedError`; callers must not depend on
  synthetic probe source.
- A missing marker, missing sandbox, timeout, or invalid test must never be
  interpreted as `refuted`.
- `confirmed` and `refuted` are reserved for verifiers with explicit,
  testable evidence contracts.

This is an intentional fail-closed capability reduction, not a claim that
vulnerabilities have been disproved. Reports should preserve the original
scanner finding and clearly label confirmation as unavailable/inconclusive.

## Requirements before restoring confirmation

A future verifier must:

1. Identify the actual target entry point and the relevant source-to-sink path.
2. Demonstrate that the candidate input reaches the operation under test.
3. Use a vulnerability-specific oracle that cannot be satisfied by the payload
   text or test harness itself.
4. Run only in a disposable, resource-limited sandbox with network disabled and
   no credentials or host mounts.
5. Capture bounded, structured evidence: target, test case, oracle, exit status,
   relevant output, timeout, and sandbox identity.
6. Return `inconclusive` when reachability, environment, oracle, or isolation
   cannot be established.
7. Include negative controls and regression tests that prove the oracle does
   not accept its own payload or fixture.

## Pull-request workflow boundary

`.github/workflows/mizan-scan.yml` is an untrusted-code analysis workflow.
It checks out source with persisted credentials disabled and runs CodeQL only.
It does not install project dependencies, execute repository scripts, receive
repository secrets, push commits, auto-fix files, or comment on pull requests.

The CodeQL job has `security-events: write` only so GitHub can receive the
analysis results. Repository contents remain read-only. Any future repair
automation must be a separate, explicitly approved workflow with narrowly
scoped permissions and must never execute untrusted pull-request code while
holding write credentials.

## CI classification

The framework test suite and its coverage threshold remain blocking.
NovaMind suites remain explicitly non-blocking reports because their separate
runtime/data setup has not yet been promoted to a reliable merge gate. This
label describes the current CI contract; it is not a statement that those
tests are unimportant or passing.
