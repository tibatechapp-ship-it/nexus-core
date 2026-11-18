# Mission output-token budgets

NEXUS can enforce an optional, durable output-token budget per mission.

## Configure a budget

Configure the budget after creating the mission and before dispatching agents:

```python
mission = org_store.create_mission(mission)
org_store.configure_mission_output_token_budget(
    mission.id,
    limit_tokens=20_000,
)
```

The shared `AgentRuntime` checks the ledger before every model attempt. It reserves the agent contract's `AgentSpec.max_tokens` in a SQLite `BEGIN IMMEDIATE` transaction. If the remaining budget cannot cover the reservation, it raises `OrgError` before calling the provider.

When a provider returns, the reservation is settled against the provider-reported output-token count. Confirmed provider-call exceptions release the reservation. Retries reserve independently, so retries are included in the same mission-wide ceiling.

## Inspect usage

```python
budget = org_store.mission_output_token_budget(mission.id)
reservations = org_store.mission_output_token_reservations(mission.id)
```

The budget record reports `limit_tokens`, `consumed_tokens`, and `reserved_tokens`.

## Guarantees and boundaries

- Reservation is atomic across concurrent workers and independent SQLite connections.
- Settlements are idempotent for the same actual token count; conflicting re-settlement is rejected.
- A configured limit cannot be lowered below already consumed plus currently reserved tokens.
- Reservation history is append-preserving and budget changes/settlements/releases are audited.
- Missions without a configured budget retain the existing unbudgeted behavior.

This feature currently limits **output tokens only**. It does not claim to cap input tokens, USD spend, provider-side hidden reasoning tokens, or total wall-clock cost. Those require provider-specific accounting contracts.

If the process crashes after reserving but before settlement, the reservation remains held. This is deliberate fail-closed behavior: the provider call's outcome may be uncertain, so the system does not silently refund capacity. A future operator reconciliation workflow must resolve such reservations with explicit evidence.
