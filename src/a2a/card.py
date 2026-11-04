"""بطاقة الوكيل A2A — تُولَّد من جرد الأسطول (مصدر واحد للحقيقة).

المواصفة المثبَّطة (docs/A2A.md): A2A 0.3.0 — حقول البطاقة المطلوبة:
``name, description, url, version, protocolVersion, capabilities,
defaultInputModes, defaultOutputModes, skills[].``
المفاتيح على الشبكة camelCase (كما في المواصفة)؛ داخليًا snake_case.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: نسخة المواصفة المستهدفة — ثابتة وموثّقة (تُرفع بمراجعة معلنة فقط).
A2A_PROTOCOL_VERSION = "0.3.0"

#: نقل البيانات المفضّل — JSONRPC فقط في هذه اللقطة.
A2A_PREFERRED_TRANSPORT = "JSONRPC"

#: الحقول الإلزامية في قاموس بطاقة (عقد conformance يعتمدها).
REQUIRED_CARD_FIELDS = (
    "name", "description", "url", "version", "protocolVersion",
    "capabilities", "defaultInputModes", "defaultOutputModes", "skills",
)

#: أوضاع الإدخال/الإخراج الافتراضية — نص فقط في هذه اللقطة.
DEFAULT_IO_MODES = ["text/plain"]


@dataclass
class AgentCard:
    """بطاقة وكيل A2A — الحقول كما في المواصفة، داخليًا snake_case."""

    name: str
    description: str
    url: str
    version: str
    skills: list[dict[str, Any]] = field(default_factory=list)
    protocol_version: str = A2A_PROTOCOL_VERSION
    preferred_transport: str = A2A_PREFERRED_TRANSPORT
    streaming: bool = False
    push_notifications: bool = False
    state_transition_history: bool = False
    input_modes: list[str] = field(default_factory=lambda: list(DEFAULT_IO_MODES))
    output_modes: list[str] = field(default_factory=lambda: list(DEFAULT_IO_MODES))

    def to_dict(self) -> dict[str, Any]:
        return card_to_dict(self)


def card_to_dict(card: AgentCard) -> dict[str, Any]:
    """حوّل البطاقة إلى شكل المواصفة (camelCase) — شكل الاختبار المرجعي."""
    return {
        "name": card.name,
        "description": card.description,
        "url": card.url,
        "version": card.version,
        "protocolVersion": card.protocol_version,
        "preferredTransport": card.preferred_transport,
        "capabilities": {
            "streaming": card.streaming,
            "pushNotifications": card.push_notifications,
            "stateTransitionHistory": card.state_transition_history,
        },
        "defaultInputModes": list(card.input_modes),
        "defaultOutputModes": list(card.output_modes),
        "skills": [dict(s) for s in card.skills],
    }


def validate_card(d: dict[str, Any]) -> list[str]:
    """تحقّق صرامة البطاقة — أعِد قائمة المشاكل (فارغة = صالحة)."""
    problems: list[str] = []
    for f in REQUIRED_CARD_FIELDS:
        if f not in d:
            problems.append(f"missing field: {f}")
    if not problems:
        if not isinstance(d["name"], str) or not d["name"]:
            problems.append("name must be a non-empty string")
        if not isinstance(d["url"], str) or not d["url"].startswith(("http://", "https://")):
            problems.append("url must be an http(s) endpoint")
        if d.get("protocolVersion") != A2A_PROTOCOL_VERSION:
            problems.append(
                f"protocolVersion must be {A2A_PROTOCOL_VERSION!r}, got "
                f"{d.get('protocolVersion')!r}")
        caps = d["capabilities"]
        if not isinstance(caps, dict) or "streaming" not in caps:
            problems.append("capabilities must include streaming flag")
        for k in ("defaultInputModes", "defaultOutputModes"):
            if not isinstance(d[k], list) or not d[k]:
                problems.append(f"{k} must be a non-empty list")
        skills = d["skills"]
        if not isinstance(skills, list) or not skills:
            problems.append("skills must be a non-empty list")
        else:
            for i, s in enumerate(skills):
                for sf in ("id", "name", "description", "tags"):
                    if sf not in s:
                        problems.append(f"skills[{i}] missing: {sf}")
    return problems


def _endpoint(root_url: str = "") -> str:
    """عنوان نقطة الرسائل — يُضبط بالنشر؛ افتراض محلي آمن للاختبار."""
    if root_url:
        return root_url.rstrip("/") + "/api/a2a/message"
    return "http://127.0.0.1:8000/api/a2a/message"


def build_agent_cards(
    endpoint_root: str = "",
    inventory: list[Any] | None = None,
) -> list[AgentCard]:
    """106 بطاقة من جرد الأسطول الحي — مصدر واحد للحقيقة.

    كل وكيل في الجرد = بطاقة: مهارتها الوحيدة هي دور الوكيل نفسه،
    والوسوم من (category, framework, role) — بلا أي قائمة موازية.
    """
    if inventory is None:
        from src.fleet.report import build_inventory
        inventory = build_inventory()
    cards: list[AgentCard] = []
    # الأسماء قد تتكرر عبر الأطر — نبدّد التكرار بإطار الوكيل فقط
    # عند الحاجة (الأسامي الفريدة تبقى قصيرة ومستقرة).
    from collections import Counter
    name_counts = Counter(rec.name for rec in inventory)
    for rec in inventory:
        skill = {
            "id": f"agent:{rec.name}",
            "name": rec.name,
            "description": rec.description or f"nexus agent {rec.name}",
            "tags": [t for t in (rec.category, rec.framework, rec.role) if t],
        }
        base = rec.name if name_counts[rec.name] == 1 else \
            f"{rec.name}.{rec.framework}"
        cards.append(AgentCard(
            name=f"nexus-{base}",
            description=rec.description or f"nexus agent {rec.name}",
            url=_endpoint(endpoint_root),
            version=_hub_version(),
            skills=[skill],
        ))
    return cards


def build_hub_card(endpoint_root: str = "") -> AgentCard:
    """بطاقة المنصة (المركز): مهاراتها = إمكانات النظام الكبرى."""
    skills = [
        {"id": "council:deliberate", "name": "council",
         "description": "مداولة مجلس 106 وكلاء بإجماع مُقاس",
         "tags": ["council", "consensus"]},
        {"id": "agent:run", "name": "agents",
         "description": "تشغيل أي وكيل من الأسطول الموحّد",
         "tags": ["agents", "fleet"]},
        {"id": "memory:query", "name": "memory",
         "description": "استرجاع من الذاكرة/RAG الدائمة",
         "tags": ["memory", "rag"]},
    ]
    return AgentCard(
        name="nexus-core",
        description="Unified AI Agent System — council of 106 agents, "
                    "durable execution, deep tracing",
        url=_endpoint(endpoint_root),
        version=_hub_version(),
        skills=skills,
    )


def _hub_version() -> str:
    """إصدار المنصة من مصدر الحقيقة الواحد (src.__version__)."""
    try:
        from src import __version__
        return str(__version__)
    except Exception:  # pragma: no cover — الاستيراد الدائري مستحيل عمليًا
        return "0.0.0"
