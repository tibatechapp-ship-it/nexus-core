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

## Important integration constraint

This PR provides the durable approval store and service only. It does not connect token consumption to ExternalEffectDispatcher yet. The dispatcher currently authorizes before reading its durable operation ledger; blindly consuming a one-time token at that point would break safe replay of an already successful operation. Integration must first establish the operation identity, return a previously persisted success without consuming a new token, and atomically consume a matching approval only for a still-prepared operation before claiming/dispatching it. That integration needs its own concurrency and crash-window tests.

No real SCM adapter, HTTP request, subprocess, or remote mutation is enabled by this feature. A consumed approval is not proof that a provider effect succeeded.
