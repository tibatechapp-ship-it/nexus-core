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
- A process interruption leaves its reservation outstanding. This intentionally fails closed; an operator must verify that no provider work remains active before releasing the reservation only through explicit reconciliation that records the operator, terminal-provider confirmation, reason, and evidence references.
- A response reporting more output tokens than reserved is rejected for settlement and leaves the reservation outstanding for reconciliation.
- Every configure, reserve, settle, release, and exhausted-budget event is recorded in the audit log.

## Scope and limitations

This is an output-token ceiling, not a total-token, dollar, wall-clock, or request-count budget. Prompt/input tokens are not included because provider tokenization differs and the current provider contract does not expose a pre-dispatch exact count. Provider pricing and actual billed cost must continue to be monitored separately.

The budget is opt-in and must be configured explicitly for each mission. A budget is not a substitute for provider-side spending limits, rate limits, or human approval for external effects.


## ربط الميزانية بدورة حياة المهمة

يمكن تحديد سقف المهمة عند الإنشاء، قبل تخطيطها أو تشغيل أي وكيل. أصبح
`Mission.output_token_limit` جزءًا من عقد المهمة ويُحفظ في سجل `missions`
(مخطط المتجر v10)، كما تُنشأ معه ميزانية الحجز في المعاملة نفسها. لا تُفعّل
ميزانية تلقائيًا للمهام القديمة أو للمهام التي لم تحدد سقفًا.

- Python: `Mission(title=..., objective=..., output_token_limit=50000)`
- CLI: `org mission --title ... --objective ... --max-output-tokens 50000`
- REST: أرسل `output_token_limit` كعدد صحيح موجب مع `POST /org/missions`.

إعادة إنشاء مهمة بالهوية نفسها وبسقف مختلف مرفوضة؛ سقف المهمة غير قابل
للتغيير بعد حفظه. تمرر نقطة تشغيل REST السقف المحفوظ إلى خط الأنابيب.
القيم المنطقية والنصية والصفر والسالب والأعداد الأكبر من حد SQLite مرفوضة.
الميزانية اختيارية، لذلك تظل المهام القديمة بلا سقف محافظة على السلوك السابق.

الحد يخص توكنات الخرج فقط؛ لا يمثل حدًا للمدخلات أو التكلفة المالية أو الزمن
أو عدد الطلبات. كل استدعاء وكيل يحجز قبل الإرسال حاصل ضرب `max_tokens` في عدد مزوّدي
البدائل المهيئين. يُحاسب كل مزوّد بديل فشل بعد احتمال الإرسال بسقف الخرج
الكامل، ثم تُضاف توكنات الرد الناجح وتُسوّى بقية الحجز. هذا متحفظ عمدًا لأن
خطأ المزوّد لا يثبت أن الطلب لم يصل أو لم ينتج خرجًا.

## Crash recovery and manual reconciliation

A reservation left in `reserved` after a process interruption is **not** expired
or released based on age. The provider request may still be executing, and a
timeout does not prove that the provider did not process it.

After independently confirming that the provider request is terminal, an
authorized operator can reconcile the reservation:

```python
store.reconcile_mission_output_tokens(
    reservation_id,
    actual_tokens=usage_recovered_from_provider,
    actor="incident-commander",
    reason="Provider request reached a terminal state; usage recovered",
    evidence_refs=["provider-log://request-id", "incident://case-id"],
    confirm_provider_terminal=True,
)
```

The operation is atomic and one-shot. It rejects missing evidence, a missing
terminal-state confirmation, usage above the reserved ceiling, and reservations
already settled or released. The reconciliation record and audit event preserve
the actor, reason, evidence references, reserved amount, and actual usage.
Reconciliation records are append-only and protected against update/delete.
If provider usage cannot be established, do not guess or release the reservation:
keep the capacity reserved and escalate for provider-side investigation.

Schema v10 adds the immutable reconciliation ledger without rewriting existing
reservation rows. The v8/v9 budget data remains intact during migration.
