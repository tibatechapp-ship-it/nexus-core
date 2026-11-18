"""Explicitly offline adapter for exercising the external-effect pipeline.

This adapter never opens sockets, invokes subprocesses, or mutates a remote
system. Its results are marked as simulations and must not be interpreted as
evidence that a real provider accepted an operation.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

from src.org.external_effects import EffectCapability


class DryRunEffectAdapter:
    """Allow-listed, deterministic adapter that records simulated requests."""

    provider_id = "dry-run"

    def __init__(self, operations: Iterable[str]) -> None:
        names = tuple(operations)
        if not names:
            raise ValueError("at least one dry-run operation must be declared")
        if any(not isinstance(name, str) or not name.strip() for name in names):
            raise ValueError("operation names must be non-empty strings")
        if len(set(names)) != len(names):
            raise ValueError("duplicate dry-run operation")
        self.capabilities = {
            name: EffectCapability(name, "none") for name in names
        }
        self._calls: list[dict[str, Any]] = []

    @property
    def calls(self) -> tuple[dict[str, Any], ...]:
        """Return defensive copies so callers cannot rewrite recorded history."""
        return tuple(json.loads(json.dumps(call)) for call in self._calls)

    def dispatch(
        self,
        operation_name: str,
        request: Mapping[str, Any],
        *,
        idempotency_key: str | None,
    ) -> Mapping[str, Any]:
        if operation_name not in self.capabilities:
            raise ValueError(f"undeclared dry-run operation: {operation_name}")
        if idempotency_key is not None:
            raise ValueError("dry-run adapter does not accept provider idempotency keys")
        if not isinstance(request, Mapping):
            raise TypeError("request must be a mapping")
        try:
            encoded = json.dumps(
                dict(request), sort_keys=True, ensure_ascii=False,
                separators=(",", ":"), allow_nan=False,
            )
            snapshot = json.loads(encoded)
        except (TypeError, ValueError) as exc:
            raise ValueError("request must contain finite JSON values") from exc

        fingerprint = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        self._calls.append({
            "operation_name": operation_name,
            "request": snapshot,
            "request_fingerprint": fingerprint,
        })
        return {
            "dry_run": True,
            "provider_id": self.provider_id,
            "operation_name": operation_name,
            "request_fingerprint": fingerprint,
            "simulated": True,
        }
