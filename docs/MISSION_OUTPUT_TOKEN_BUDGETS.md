# Mission output-token budgets

Mission budgets provide a durable, shared ceiling for **model response/output tokens** across all agents in one mission.

## Configure a budget

Configure the budget after creating the mission and before dispatching agent work:

```python
store.configure_mission_token_budget(mission.id, output_token_limit=40_000)
```

The limit is immutable after creation. Existing missions without a configured budget retain their previous behavior. Once configured, `AgentRuntime` automatically reserves each agent call's `AgentSpec.max_tokens` before contacting the provider.

## Accounting and failure behavior

- Reservations are written in SQLite inside `BEGIN IMMEDIATE`, so independent workers cannot reserve the same remaining capacity.
- Successful responses settle the reservation using the provider-reported output-token usage.
- Provider errors are charged at the full reserved ceiling because the runtime cannot prove that the request failed before dispatch.
- A process interruption leaves its reservation outstanding. This intentionally fails closed; an operator must verify that no provider work remains active before releasing the reservation with an auditable reason.
- A response reporting more output tokens than reserved is rejected for settlement and leaves the reservation outstanding for reconciliation.
- Every configure, reserve, settle, release, and exhausted-budget event is recorded in the audit log.

## Scope and limitations

This is an output-token ceiling, not a total-token, dollar, wall-clock, or request-count budget. Prompt/input tokens are not included because provider tokenization differs and the current provider contract does not expose a pre-dispatch exact count. Provider pricing and actual billed cost must continue to be monitored separately.

The budget is opt-in and must be configured explicitly for each mission. A budget is not a substitute for provider-side spending limits, rate limits, or human approval for external effects.
