"""الطبقة الشكلية — «المُقترح يبحث، والحاكم يحكم».

ثلاثة حكّام صادقة فوق عقد حاكم واحد:
  * ``model_checker``  — مستوى TLA+/TLC: تعداد حالات محدود بميزانيتين
    معلنتين، متغيرات سلامة، استقرار محدود، أثر خالق كامل عند الرفض.
  * ``contract_checker`` — مستوى Dafny: شروط مسبقة/لاحقة محاومة
    بالسرد المحدود على مجال معلن؛ مجال عاقر = UNKNOWN لا قبول فارغ.
  * ``prover_loop`` — مستوى AlphaProof Nexus: مولّد يبحث، الحاكم
    يحكم، مصلح موجّه بالدليل، منهي بميزانية صارمة.

الخرائط المرجعية الكاملة مع الحدود الصادقة: ``docs/FORMAL_REFERENCE.md``.
أكواد الخروج في ``cli``: 0 قبول، 1 رفض، 2 تعذّر التحقق — عقد MIZAN نفسه.
"""

from __future__ import annotations

from src.formal.contract_checker import (
    Contract,
    ContractReport,
    InputSpace,
    check_contract,
)
from src.formal.judge import (
    FormalError,
    FormalRejection,
    Judge,
    PredicateJudge,
    Verdict,
    VerdictKind,
    all_accept,
    evidence_lines,
)
from src.formal.model_checker import (
    ModelReport,
    SafetyInvariant,
    StabilityGoal,
    TransitionSystem,
    check_safety,
    check_stability,
    check_system,
    handoff_protocol_demo,
)
from src.formal.prover_loop import (
    Attempt,
    CounterexampleGuidedGenerator,
    Generator,
    LoopReport,
    StaticGenerator,
    run_prover_loop,
)

__all__ = [
    "Attempt",
    "Contract",
    "ContractReport",
    "CounterexampleGuidedGenerator",
    "FormalError",
    "FormalRejection",
    "Generator",
    "InputSpace",
    "Judge",
    "LoopReport",
    "ModelReport",
    "PredicateJudge",
    "SafetyInvariant",
    "StabilityGoal",
    "StaticGenerator",
    "TransitionSystem",
    "Verdict",
    "VerdictKind",
    "all_accept",
    "check_contract",
    "check_safety",
    "check_stability",
    "check_system",
    "evidence_lines",
    "handoff_protocol_demo",
    "run_prover_loop",
]
