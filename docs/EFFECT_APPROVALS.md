# Durable scoped external-effect approvals

## Purpose

Schema v7 adds a durable approval primitive for a single external effect. An approval is bound to the mission and task, repository, ref, commit, provider, operation, canonical JSON request fingerprint, and one authenticated executor principal. It is not a general-purpose permission and cannot authorize a different payload or target.

## Trust boundaries

Construct EffectApprovalService with two injected callbacks: a principal verifier backed by the application's trusted session or identity provider, and an approval policy that enforces approver roles, scope, and separation of duties. Never implement identity verification as a truthiness check on a caller-supplied actor string or trust a display name supplied by an API client.

The issuer and executor are verified separately. The approval record stores both identities; only the executor principal bound at issuance can consume it.

## Token lifecycle

1. An authorized human approver issues a short-lived token for an exact scope.
2. The service returns the high-entropy token once. SQLite stores only its SHA-256 digest; do not log or persist the returned token in application logs.
3. Immediately before an external effect, the authenticated executor presents the token and the complete scope/request.
4. SQLite consumes it atomically under BEGIN IMMEDIATE. Concurrent attempts have one winner. Replay, wrong principal, scope/payload mismatch, expiry, and revocation are rejected.
5. Revocation is permitted only through the same injected approval policy. Issued, consumed, expired, and revoked transitions are audited.

## Dispatcher integration

ExternalEffectDispatcher accepts an injected EffectApprovalService for durable one-time authorization. In this mode, execute() requires the authenticated executor principal plus the approval token and the exact repository, ref, and commit scope.

The dispatcher first persists/loads the immutable operation identity. If the ledger already contains succeeded or reconciled, it returns that stored result without requiring or consuming another token. For a prepared operation, EffectApprovalService.consume_and_claim() delegates to OrgStore.claim_external_operation_with_approval(); the store validates the token digest, scope, executor, expiry, and issued status, then consumes the approval and creates the fenced in-flight attempt inside one SQLite BEGIN IMMEDIATE transaction. A scope mismatch leaves the token available. An abandoned in-flight operation remains blocked and requires explicit reconciliation; its consumed approval is not reusable.

The older injected authorizer remains supported for existing integrations. Production applications should prefer the durable service and must construct its principal verifier from a trusted identity/session provider and its approval policy from enforceable approver roles and separation-of-duties rules. Never pass a caller-controlled display name as authenticated identity.

No real SCM adapter, HTTP request, subprocess, or remote mutation is enabled by this feature. A consumed approval is not proof that a provider effect succeeded.
