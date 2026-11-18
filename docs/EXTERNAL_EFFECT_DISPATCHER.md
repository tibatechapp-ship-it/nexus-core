# Ledger-backed external-effect dispatcher

## Status

This slice adds a provider-neutral dispatcher over the organization store's
durable external-operation ledger. It does not add a GitHub or GitLab writer,
does not issue network requests, and does not enable automatic retries.

## Dispatch sequence

1. Resolve the adapter's explicit capability for the exact operation name.
2. Ask the application-supplied authorizer to verify an authenticated human
   approval bound to actor, mission, task, operation and request.
3. Persist the stable operation identity and canonical request fingerprint.
4. Atomically claim the prepared operation with a fenced attempt token.
5. Pass the stable operation key only when the adapter declares a documented
   provider idempotency-key capability for that operation.
6. Dispatch exactly once and persist success, definitive rejection or an
   uncertain outcome.
7. Return an already persisted success without dispatching a second time.

An adapter with no provider idempotency guarantee receives no key. That does
not prevent its first explicitly approved dispatch; it means an uncertain
outcome is never retried automatically.

## Failure semantics

- A DefinitiveEffectError means the adapter has reliable provider evidence
  that the effect was rejected. The ledger records failed_definitive.
- Any other adapter exception is conservatively treated as uncertain. The
  ledger records uncertain; a subsequent call is blocked.
- A process crash after claim but before finalization leaves in_flight.
  Recovery must inspect the provider and use the existing explicit
  evidence-backed reconciliation API. This dispatcher never takes over a
  stale attempt.
- A changed request under the same mission/task/operation/revision identity is
  rejected by the ledger fingerprint check.
- A stored succeeded or reconciled operation returns its persisted result.

## Application integration boundary

The authorizer is mandatory and injected by the application. It must validate
the authenticated principal and a real approval record for the exact payload.
The dispatcher does not authenticate users, create approvals, or treat a
caller-provided boolean as proof of identity.

No production SCM adapter implements this contract in this slice. The next
step is a recording/fake provider contract test, followed by a provider-specific
writer only after the provider's idempotency and reconciliation semantics are
documented and independently reviewed.

## Guarantees we do not claim

The local ledger prevents this application from blindly redispatching an
uncertain operation. It cannot by itself guarantee exactly-once delivery across
a network boundary. Provider-side idempotency is only as strong as the
provider's documented scope and retention period. This slice does not provide
automatic retry even when a provider key is available.
