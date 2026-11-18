"""Ledger-backed dispatch for explicitly authorized external effects.

This module is deliberately provider-neutral. It connects the durable
external-operation state machine to a narrow adapter contract without enabling
any concrete network mutation by default.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Callable, Literal, Mapping, Protocol

from src.org.effect_approvals import EffectApprovalService
from src.org.store import OrgError, OrgStore

__all__ = [
    "EffectCapability",
    "EffectDispatchError",
    "EffectNotAuthorized",
    "EffectResult",
    "EffectUncertain",
    "ExternalEffectAdapter",
    "ExternalEffectDispatcher",
    "DefinitiveEffectError",
]


IdempotencyMode = Literal["provider_key", "none"]


@dataclass(frozen=True)
class EffectCapability:
    """Provider guarantee for one named logical operation.

    provider_key means the adapter documents and implements the supplied
    stable key for this exact operation. none means one dispatch only:
    uncertain outcomes must be reconciled, never blindly retried.
    """

    operation_name: str
    idempotency_mode: IdempotencyMode
    idempotency_scope: str = ""
    retention_seconds: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.operation_name, str) or not self.operation_name.strip():
            raise ValueError("operation_name is required")
        if self.idempotency_mode not in {"provider_key", "none"}:
            raise ValueError("unsupported idempotency_mode")
        if self.idempotency_mode == "provider_key":
            if not isinstance(self.idempotency_scope, str) or not self.idempotency_scope.strip():
                raise ValueError("provider-key capability requires a documented scope")
            if type(self.retention_seconds) is not int or self.retention_seconds <= 0:
                raise ValueError("provider-key capability requires a documented positive retention")
        elif self.idempotency_scope or self.retention_seconds != 0:
            raise ValueError("idempotency metadata is invalid when mode is none")


class ExternalEffectAdapter(Protocol):
    """A single provider adapter with explicit per-operation capabilities."""

    provider_id: str
    capabilities: Mapping[str, EffectCapability]

    def dispatch(
        self,
        operation_name: str,
        request: Mapping[str, Any],
        *,
        idempotency_key: str | None,
    ) -> Mapping[str, Any]:
        """Perform exactly one provider request and return a JSON-safe result."""


class DefinitiveEffectError(RuntimeError):
    """The provider definitively rejected the operation; no effect occurred."""


class EffectDispatchError(RuntimeError):
    """The operation could not be dispatched safely."""


class EffectNotAuthorized(EffectDispatchError):
    """The application's human-approval authorizer denied the operation."""


class EffectUncertain(EffectDispatchError):
    """The provider outcome may have committed; automatic redispatch is blocked."""


@dataclass(frozen=True)
class EffectResult:
    operation_key: str
    state: str
    result: dict[str, Any]
    reused: bool
    provider_id: str


Authorizer = Callable[[str, str, str, str, str, Mapping[str, Any]], bool]


class ExternalEffectDispatcher:
    """One-shot, approval-gated bridge from OrgStore to a provider adapter.

    The injected authorizer must validate an authenticated human approval for
    this exact mission, task, operation and request. A boolean supplied by an
    untrusted caller is not an authorization mechanism. No concrete adapter is
    included in this slice, and this class never retries a provider call.
    """

    def __init__(
        self,
        store: OrgStore,
        adapter: ExternalEffectAdapter,
        *,
        worker_id: str,
        authorizer: Authorizer | None = None,
        approval_service: EffectApprovalService | None = None,
    ) -> None:
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise ValueError("worker_id is required")
        if not isinstance(getattr(adapter, "provider_id", None), str) or not adapter.provider_id.strip():
            raise ValueError("adapter.provider_id is required")
        if not callable(authorizer) and approval_service is None:
            raise ValueError("an application approval authorizer or durable approval service is required")
        self._store = store
        self._adapter = adapter
        self._worker_id = worker_id.strip()
        self._authorizer = authorizer
        self._approval_service = approval_service

    def execute(
        self,
        mission_id: str,
        task_id: str,
        operation_name: str,
        revision: str,
        request: Mapping[str, Any],
        *,
        actor: str,
        approval_token: str | None = None,
        repository: str | None = None,
        ref_name: str | None = None,
        commit_sha: str | None = None,
    ) -> EffectResult:
        """Authorize, persist, claim, dispatch once, and durably record outcome."""
        if not isinstance(actor, str) or not actor.strip():
            raise EffectNotAuthorized("authenticated actor is required")
        if not isinstance(request, Mapping):
            raise EffectDispatchError("request must be a mapping")
        capability = self._adapter.capabilities.get(operation_name)
        if capability is None or capability.operation_name != operation_name:
            raise EffectDispatchError(
                f"provider {self._adapter.provider_id} does not declare {operation_name}"
            )
        try:
            encoded_request = json.dumps(
                dict(request), sort_keys=True, ensure_ascii=False,
                separators=(",", ":"), allow_nan=False,
            )
            payload = json.loads(encoded_request)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise EffectDispatchError("request must contain finite JSON values") from exc
        ledger_operation_name = f"{self._adapter.provider_id}:{operation_name}"
        ledger_revision = revision
        if self._approval_service is not None:
            scope_values = (repository, ref_name, commit_sha)
            if not all(isinstance(value, str) and value.strip() for value in scope_values):
                raise EffectNotAuthorized(
                    "durable approval repository, ref, and commit are required"
                )
            try:
                self._approval_service.verify_executor(actor.strip())
            except Exception as exc:
                raise EffectNotAuthorized("executor identity was not verified") from exc
            target = json.dumps(
                [repository, ref_name, commit_sha],
                ensure_ascii=False, separators=(",", ":"), allow_nan=False,
            )
            target_fingerprint = hashlib.sha256(target.encode("utf-8")).hexdigest()
            ledger_revision = f"{revision}:{target_fingerprint}"
        # Legacy integrations retain their injected authorizer. Durable
        # one-time approvals are consumed only after operation identity is
        # persisted and only when the ledger still says "prepared".
        if self._approval_service is None:
            try:
                allowed = self._authorizer(
                    actor.strip(), mission_id, task_id, self._adapter.provider_id,
                    operation_name, json.loads(encoded_request),
                )
            except Exception as exc:
                raise EffectNotAuthorized(
                    f"approval authorization failed: {type(exc).__name__}"
                ) from exc
            if allowed is not True:
                raise EffectNotAuthorized("human approval was not verified")

        prepared = self._store.prepare_external_operation(
            mission_id, task_id, ledger_operation_name, ledger_revision, payload
        )
        operation_key = str(prepared["operation_key"])
        state = str(prepared["state"])
        if state in {"succeeded", "reconciled"}:
            return EffectResult(
                operation_key=operation_key,
                state=state,
                result=self._decode_result(prepared.get("result_payload")),
                reused=True,
                provider_id=self._adapter.provider_id,
            )
        if state == "failed_definitive":
            raise EffectDispatchError("operation previously failed definitively")
        if state != "prepared":
            raise EffectUncertain(
                f"operation is {state}; inspect or reconcile it before any new dispatch"
            )

        if self._approval_service is not None:
            if not isinstance(approval_token, str) or not approval_token.strip():
                raise EffectNotAuthorized("durable one-time approval token is required")
            try:
                claim = self._approval_service.consume_and_claim(
                    approval_token,
                    executor_principal_id=actor.strip(),
                    mission_id=mission_id, task_id=task_id,
                    repository=repository, ref_name=ref_name,
                    commit_sha=commit_sha, provider_id=self._adapter.provider_id,
                    operation_name=operation_name, request=payload,
                    operation_key=operation_key, worker_id=self._worker_id,
                )
            except Exception as exc:
                raise EffectNotAuthorized(
                    f"durable effect approval rejected: {type(exc).__name__}"
                ) from exc
            if claim.get("reused") is True:
                operation = claim["operation"]
                return EffectResult(
                    operation_key=operation_key,
                    state=str(operation["state"]),
                    result=self._decode_result(operation.get("result_payload")),
                    reused=True,
                    provider_id=self._adapter.provider_id,
                )
        else:
            claim = self._store.claim_external_operation(operation_key, self._worker_id)
        idempotency_key = (
            operation_key if capability.idempotency_mode == "provider_key" else None
        )
        try:
            raw_result = self._adapter.dispatch(
                operation_name, json.loads(encoded_request), idempotency_key=idempotency_key
            )
            if not isinstance(raw_result, Mapping):
                raise TypeError("provider result must be a mapping")
            result = dict(raw_result)
            finalized = self._store.finish_external_operation(
                operation_key, claim["attempt_token"],
                state="succeeded", result=result,
            )
        except DefinitiveEffectError as exc:
            self._store.finish_external_operation(
                operation_key, claim["attempt_token"],
                state="failed_definitive", error=type(exc).__name__,
            )
            raise EffectDispatchError(
                f"provider definitively rejected operation: {type(exc).__name__}"
            ) from exc
        except Exception as exc:
            # A timeout or transport error is not proof that the provider did
            # not commit. Do not leak provider exception text into durable logs.
            try:
                self._store.finish_external_operation(
                    operation_key, claim["attempt_token"],
                    state="uncertain", error=type(exc).__name__,
                )
            except OrgError:
                # Preserve the original uncertainty; a later operator can
                # inspect the still-in-flight row and mark it uncertain.
                pass
            raise EffectUncertain(
                "provider outcome is unknown; automatic redispatch is blocked"
            ) from exc

        return EffectResult(
            operation_key=operation_key,
            state=str(finalized["state"]),
            result=self._decode_result(finalized.get("result_payload")),
            reused=False,
            provider_id=self._adapter.provider_id,
        )

    @staticmethod
    def _decode_result(value: Any) -> dict[str, Any]:
        import json

        if not isinstance(value, str) or not value:
            return {}
        try:
            decoded = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return {}
        return decoded if isinstance(decoded, dict) else {}
