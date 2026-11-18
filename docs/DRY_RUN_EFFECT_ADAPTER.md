# Offline dry-run external-effect adapter

`DryRunEffectAdapter` is a local adapter for exercising the existing
approval-gated dispatcher and durable ledger without contacting a provider.

## Safety properties

- It performs no HTTP requests, socket operations, subprocess calls, or remote
  mutations.
- Its operation set is an explicit allow-list supplied at construction.
- Every capability declares `idempotency_mode="none"`; no provider key is
  accepted or emitted.
- Requests must be finite JSON values and are recorded as defensive snapshots.
- Results always contain `dry_run: true` and `simulated: true`. They are
  simulation output, not provider receipts, remote identifiers, or evidence of
  a completed real-world effect.
- The adapter must never be configured as a production SCM provider.

## Example

```python
from src.org.dry_run_effects import DryRunEffectAdapter

adapter = DryRunEffectAdapter(["comment", "open_change"])
result = adapter.dispatch(
    "comment",
    {"repository": "owner/repo", "body": "simulation"},
    idempotency_key=None,
)
assert result["dry_run"] is True
```

For dispatcher-level tests, inject this adapter with an application authorizer
that explicitly permits the test request. The dispatcher still persists the
simulation in the external-operation ledger; use a dedicated test database and
do not treat a succeeded dry-run ledger row as a real remote success.

This adapter is deliberately not a GitHub/GitLab writer. Real provider
integration remains a separate security-reviewed change.
