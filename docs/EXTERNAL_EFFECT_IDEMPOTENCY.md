# External effect idempotency contract

## Status and scope

This document defines the safety contract for future task-driven external
mutations. It does not claim that the current GitHub/GitLab autopilot adapters
perform writes: the current `SCM` adapters are read-only and issue GET requests.
The `SCMWriter` protocol is declared separately, but provider write adapters
are not implemented in this slice.

The organization task store already persists an `idempotency_key` for a
claimed task. That key is not, by itself, an exactly-once guarantee: it is not
currently propagated through a durable operation ledger and a provider-specific
mutation contract.

## Classify operations before applying retries

Every outbound call must be classified explicitly:

| Class | Example | Retry policy |
|---|---|---|
| Read-only | list issues, fetch a pull request | Retry according to bounded transient-error policy |
| Model inference | chat/completions request | Treat as billable and potentially duplicated; record each provider attempt; never describe it as an exactly-once mutation |
| External mutation | create issue, post comment, open change, deploy, send notification | Require a stable operation key and provider capability declaration before automatic retry |
| Local deterministic work | parse, static analysis, calculate diff | Safe to rerun when inputs are unchanged |

HTTP method alone is not a sufficient classifier. A POST inference request is
not equivalent to creating a remote issue; it may still incur duplicate cost.

## Required mutation identity

A mutation identity must be stable across process restarts and retries, and
must identify one logical effect rather than one network attempt. Derive it
from immutable persisted values:

- mission ID;
- task ID;
- logical operation name;
- operation revision / explicit sequence when the same task intentionally
  performs the same operation more than once.

Do not include worker ID, lease token, timestamp, retry count, or random values
in the stable operation identity. Those identify attempts, not the effect.

Persist a canonical request fingerprint alongside the key. Reusing a key with
a different target, payload, or operation name must be rejected as a conflict.

## Durable operation state machine

A future mutation ledger should use a transactionally claimed record with at
least these states:

- `prepared`: key and request fingerprint are persisted before network I/O;
- `in_flight`: a worker owns a fenced attempt token;
- `succeeded`: provider success and normalized result reference are persisted;
- `failed_definitive`: provider definitively rejected the operation;
- `uncertain`: timeout, connection loss, or process death means the provider
  may have committed the effect;
- `reconciled`: an operator or provider lookup established the outcome.

A stale worker must not overwrite a newer attempt. Completion must compare the
attempt token, and a request fingerprint mismatch must fail closed.

## Retry and recovery rules

1. A provider with documented idempotency-key support may receive the stable
   key using its documented header or request field. The adapter must declare
   the exact scope and retention semantics of that provider guarantee.
2. A provider without idempotency support must not be automatically retried
   after an uncertain outcome. Query by a provider-side unique marker when
   supported; otherwise require explicit operator reconciliation.
3. A timeout is not proof that the remote operation failed.
4. A local ledger prevents duplicate dispatch by this application, but cannot
   alone guarantee exactly-once effects across a network boundary.
5. Human approval remains required for release, merge, deployment, and other
   privileged actions according to the existing policy.
6. Provider capability must be explicit per operation. Never infer it from
   HTTP method, vendor name, or a generic OpenAI-compatible interface.

## Model inference accounting

Model calls are not to be silently folded into the mutation ledger. The agent
runtime already records provider/model, attempt count, token usage, cost, and
latency in agent-run records. The next hardening step for inference is to make
attempt identity and uncertain/billing outcomes explicit, and to ensure the
recording failure policy is deliberate. A provider timeout can still mean a
billable request was processed even when no response was received.

The runtime currently retries provider errors and malformed JSON responses.
Those retries can create additional billable inference calls. The product must
report observed usage separately from estimated or unknown usage; a missing
response must not be reported as zero-cost proof.

## Acceptance criteria for implementation

- [ ] Mutation adapters declare per-operation idempotency capabilities.
- [ ] A stable key and canonical request fingerprint are persisted before dispatch.
- [ ] Same key + same fingerprint returns the stored outcome or blocks safely.
- [ ] Same key + different fingerprint is rejected.
- [ ] Crash after remote success but before local commit enters an uncertain
      state and does not trigger blind retry.
- [ ] Stale attempt tokens cannot finalize an operation.
- [ ] Provider-specific tests cover supported idempotency headers/fields and
      unsupported-provider reconciliation.
- [ ] Integration tests simulate timeout-after-commit and process restart.
- [ ] Documentation explicitly avoids claiming global exactly-once delivery.
- [ ] No release, merge, deployment, or other privileged mutation bypasses
      human approval.

## Implementation order

1. Introduce the operation ledger and state-machine tests in the organization
   store without wiring any network mutation.
2. Add a capability contract to `SCMWriter` and implement one provider adapter
   at a time, using provider documentation and recording transports.
3. Add crash-window and timeout-after-commit integration tests.
4. Separately harden model-inference attempt accounting and cost uncertainty.
5. Enable mutation dispatch only after security review and explicit approval
   policy tests pass.
