"""Durable, one-time approvals for narrowly scoped external effects."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import secrets
from typing import Any, Callable, Mapping
from uuid import uuid4

from src.org.store import OrgError, OrgStore

__all__ = ["EffectApproval", "EffectApprovalError", "EffectApprovalService"]


class EffectApprovalError(RuntimeError):
    """An approval is invalid, expired, revoked, or outside its bound scope."""


@dataclass(frozen=True)
class EffectApproval:
    approval_id: str
    token: str
    expires_at: str


class EffectApprovalService:
    """Issue and atomically consume scoped, short-lived, one-time approvals."""

    def __init__(self, store: OrgStore, *,
                 principal_verifier: Callable[[str], bool],
                 approval_policy: Callable[[str, Mapping[str, str]], bool],
                 max_ttl_seconds: int = 3600) -> None:
        if not callable(principal_verifier) or not callable(approval_policy):
            raise ValueError("trusted principal verifier and approval policy are required")
        if type(max_ttl_seconds) is not int or not 1 <= max_ttl_seconds <= 86400:
            raise ValueError("max_ttl_seconds must be between 1 and 86400")
        self._store = store
        self._verify = principal_verifier
        self._policy = approval_policy
        self._max_ttl = max_ttl_seconds

    @staticmethod
    def _canonical(value: Mapping[str, Any]) -> str:
        try:
            return json.dumps(dict(value), sort_keys=True, ensure_ascii=False,
                              separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise EffectApprovalError("approval scope must contain finite JSON values") from exc

    @classmethod
    def _scope(cls, *, mission_id: str, task_id: str, repository: str,
               ref_name: str, commit_sha: str, provider_id: str,
               operation_name: str, request: Mapping[str, Any],
               executor_principal_id: str) -> tuple[str, str]:
        fields = {
            "mission_id": mission_id, "task_id": task_id,
            "repository": repository, "ref_name": ref_name,
            "commit_sha": commit_sha, "provider_id": provider_id,
            "operation_name": operation_name,
        }
        if not isinstance(executor_principal_id, str) or not executor_principal_id.strip():
            raise EffectApprovalError("executor principal is required")
        if not all(isinstance(v, str) and v.strip() for v in fields.values()):
            raise EffectApprovalError("all approval identity and target fields are required")
        payload = cls._canonical(request)
        payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        scope = {**fields, "payload_fingerprint": payload_hash}
        scope_hash = hashlib.sha256(cls._canonical(scope).encode("utf-8")).hexdigest()
        return scope_hash, payload_hash

    def _principal(self, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise EffectApprovalError("authenticated principal is required")
        principal = value.strip()
        try:
            valid = self._verify(principal)
        except Exception as exc:
            raise EffectApprovalError("principal verification failed") from exc
        if valid is not True:
            raise EffectApprovalError("principal is not authenticated")
        return principal

    def issue(self, *, issuer_principal_id: str, executor_principal_id: str,
              mission_id: str, task_id: str, repository: str, ref_name: str,
              commit_sha: str, provider_id: str, operation_name: str,
              request: Mapping[str, Any], ttl_seconds: int = 300) -> EffectApproval:
        issuer = self._principal(issuer_principal_id)
        executor = self._principal(executor_principal_id)
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= self._max_ttl:
            raise EffectApprovalError("approval TTL exceeds the permitted limit")
        scope_hash, payload_hash = self._scope(
            mission_id=mission_id, task_id=task_id, repository=repository,
            ref_name=ref_name, commit_sha=commit_sha, provider_id=provider_id,
            operation_name=operation_name, request=request,
            executor_principal_id=executor)
        policy_scope = {
            "mission_id": mission_id, "task_id": task_id,
            "repository": repository, "ref_name": ref_name,
            "commit_sha": commit_sha, "provider_id": provider_id,
            "operation_name": operation_name,
            "payload_fingerprint": payload_hash,
            "executor_principal_id": executor,
        }
        try:
            allowed = self._policy(issuer, policy_scope)
        except Exception as exc:
            raise EffectApprovalError("approval policy evaluation failed") from exc
        if allowed is not True:
            raise EffectApprovalError("issuer is not authorized to approve this effect")
        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(seconds=ttl_seconds)).isoformat(timespec="microseconds")
        approval_id = str(uuid4())
        self._store.create_effect_approval(
            approval_id=approval_id, token_digest=digest,
            scope_fingerprint=scope_hash, mission_id=mission_id, task_id=task_id,
            repository=repository, ref_name=ref_name, commit_sha=commit_sha,
            provider_id=provider_id, operation_name=operation_name,
            payload_fingerprint=payload_hash, principal_id=executor,
            issuer_principal_id=issuer, expires_at=expires)
        return EffectApproval(approval_id, token, expires)

    def consume(self, token: str, *, executor_principal_id: str,
                mission_id: str, task_id: str, repository: str, ref_name: str,
                commit_sha: str, provider_id: str, operation_name: str,
                request: Mapping[str, Any]) -> dict[str, Any]:
        executor = self._principal(executor_principal_id)
        if not isinstance(token, str) or not token:
            raise EffectApprovalError("one-time approval token is required")
        scope_hash, _ = self._scope(
            mission_id=mission_id, task_id=task_id, repository=repository,
            ref_name=ref_name, commit_sha=commit_sha, provider_id=provider_id,
            operation_name=operation_name, request=request,
            executor_principal_id=executor)
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        try:
            return self._store.consume_effect_approval(
                token_digest=digest, scope_fingerprint=scope_hash,
                principal_id=executor, now=now)
        except OrgError as exc:
            raise EffectApprovalError(str(exc)) from exc

    def consume_and_claim(self, token: str, *, executor_principal_id: str,
                          mission_id: str, task_id: str, repository: str,
                          ref_name: str, commit_sha: str, provider_id: str,
                          operation_name: str, request: Mapping[str, Any],
                          operation_key: str, worker_id: str) -> dict[str, Any]:
        """Atomically consume this approval while claiming its durable operation.

        The store returns a persisted success without consuming a fresh token.
        For a prepared operation, token consumption and claim share one
        SQLite transaction; this method must be used by the dispatcher rather
        than calling consume() followed by claim_external_operation().
        """
        executor = self._principal(executor_principal_id)
        if not isinstance(token, str) or not token:
            raise EffectApprovalError("one-time approval token is required")
        scope_hash, _ = self._scope(
            mission_id=mission_id, task_id=task_id, repository=repository,
            ref_name=ref_name, commit_sha=commit_sha, provider_id=provider_id,
            operation_name=operation_name, request=request,
            executor_principal_id=executor)
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        try:
            return self._store.claim_external_operation_with_approval(
                operation_key, worker_id, token_digest=digest,
                scope_fingerprint=scope_hash, principal_id=executor, now=now)
        except OrgError as exc:
            raise EffectApprovalError(str(exc)) from exc

    def revoke(self, approval_id: str, *, issuer_principal_id: str,
               reason: str) -> None:
        issuer = self._principal(issuer_principal_id)
        row = self._store.effect_approval_get(approval_id)
        if row is None:
            raise EffectApprovalError("تفويض غير موجود")
        policy_scope = {
            "mission_id": row["mission_id"], "task_id": row["task_id"],
            "repository": row["repository"], "ref_name": row["ref_name"],
            "commit_sha": row["commit_sha"], "provider_id": row["provider_id"],
            "operation_name": row["operation_name"],
            "payload_fingerprint": row["payload_fingerprint"],
            "executor_principal_id": row["principal_id"],
        }
        try:
            allowed = self._policy(issuer, policy_scope)
        except Exception as exc:
            raise EffectApprovalError("revocation policy evaluation failed") from exc
        if allowed is not True:
            raise EffectApprovalError("issuer is not authorized to revoke this effect")
        try:
            self._store.revoke_effect_approval(
                approval_id, principal_id=issuer, reason=reason)
        except OrgError as exc:
            raise EffectApprovalError(str(exc)) from exc
