# Independent Review and Repair Evaluation

## Independent reviewer

`src.coder.reviewer.review_patch` calls a separately identified reviewer
provider/model and validates a strict JSON verdict. The reviewer receives only
the patch and bounded evidence; it cannot edit files, execute commands, or merge.
Provider identity must differ from the patch-author identity. Critical/high
findings override an attempted approval and become `request_changes`.

This is an integration contract, not a bundled model. A deployment must
configure a genuinely separate provider/model and retain the returned verdict
with the run's audit record. Two prompts to the same model do not qualify.

## Repair benchmark

`src.coder.evaluation.evaluate_tasks` accepts deterministic task records:
- `id`: stable task identifier.
- `files`: initial workspace files mapped to UTF-8 contents.
- `patches`: exact, unique textual replacements (`path`, `find`, `replace`).
- `expected_files`: expected final file contents.
- `test_command`: argv array; shell strings are not accepted.

The runner checks exact patch output and then invokes an injected executor.
There is deliberately no host-process fallback. Use `container_executor` with
`run_in_container`, an immutable image digest, explicit feature opt-in and
human approval. Reports include task pass rate, per-task verdicts, exit status,
timeout, bounded output and total duration.

The initial harness measures deterministic patch correctness and test execution.
It does not claim SWE-bench coverage, model capability scores, pass@k, or
statistical significance. Those require a curated, versioned task corpus and
repeated runs. Add benchmark tasks only with reproducible setup and expected
outcomes; do not put secrets or network-dependent fixtures in the corpus.

## Isolation boundary

The evaluator itself never runs candidate commands. The configured executor
must be the Docker adapter, with the existing sandbox restrictions: immutable
image digest, network disabled, read-only root filesystem, dropped Linux
capabilities, no-new-privileges, non-root UID, resource/pid limits and bounded
time/output. Docker daemon rootless mode and host kernel/runtime hardening are
deployment prerequisites to verify operationally; the adapter must not be
described as a VM or a complete defense against kernel vulnerabilities.

## Acceptance

- Same provider/model identity for author and reviewer is rejected.
- Invalid reviewer JSON/schema is rejected.
- Critical/high findings cannot coexist with an approval verdict.
- Missing isolated executor fails closed.
- Patch operations reject traversal and non-unique matches.
- Benchmark results expose task pass rate and per-task evidence.
