"""وقت تشغيل الوكلاء — عقد واحد لكل وكيل في التنظيم.

القواعد المعلنة:

* **عقد وكيل معلن**: كل وكيل ``AgentSpec`` — دوره وقسمه وأدواته
  المسموحة وسلسلة نماذجه وسقوف محاولاته وزمنه وحدود ذاكرته. لا وكيل
  بلا عقد، ولا أداة خارج القائمة المسموحة.
* **أدوات بصلاحيات صريحة**: استدعاء أداة غير مسموحة يرفع
  ``PermissionError`` — التفويض قائمة أسماء معلنة لا لطف وقت التشغيل.
* **حدود ذاكرة محكومة**: الوكيل يقرأ ويكتب مفتاحًا معلنًا في نطاق
  مهمته فقط — ذاكرة مهمة قصيرة العمر لا تسرّب بين المهام.
* **إعادة محاولة مع سقف وبدائل**: كل استدعاء نموذج يجرب سلسلة النماذج
  ثم يعيد حتى ``max_retries``؛ تجاوز السقف فشل صريح يُسجَّل ولا يُخفى.
* **كل تشغيل يترك سجلًا**: تشغيل وكيل واحد = سطر ``agent_runs`` في
  المتجر بدوره ونموذجه وتوكناته وكلفته وزمنه ومحاولاته.
"""

from __future__ import annotations

import json
import re
import time
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any, Callable

from src.org.contracts import DEPARTMENTS
from src.org.providers import ModelResponse, ProviderError, ProviderPool
from src.org.store import OrgStore

__all__ = [
    "AgentOutcome",
    "AgentRuntime",
    "AgentSpec",
    "MemoryScope",
    "Tool",
    "ToolDenied",
    "ToolRegistry",
]

_JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)
_ACTIVE_TASK_LEASE: ContextVar[dict[str, Any] | None] = ContextVar(
    "nexus_active_task_lease", default=None)


class ToolDenied(PermissionError):
    """رفض أداة — الوكيل طلب أداة خارج قائمة عقده المسموحة."""


@dataclass(frozen=True)
class AgentSpec:
    """عقد وكيل — هوية وأدوات وحدود معلنة قبل أي تشغيل."""

    role: str                       # مثل dev:backend أو review:logic
    dept: str                       # واحد من DEPARTMENTS
    mission_id: str
    task_id: str = ""
    tools: frozenset[str] = frozenset()
    models: list[str] = field(default_factory=list)   # سلسلة البدائل
    max_retries: int = 2
    timeout_s: float = 90.0
    temperature: float = 0.2
    max_tokens: int = 2000
    memory_keys: frozenset[str] = frozenset()         # حدود الذاكرة المعلنة

    def __post_init__(self) -> None:
        if not isinstance(self.role, str) or ":" not in self.role:
            raise ValueError(f"دور الوكيل يجب أن يكون بصيغة قسم:عمل — {self.role!r}")
        if self.dept not in DEPARTMENTS:
            raise ValueError(
                f"قسم غير معلن: {self.dept} — المعلن {DEPARTMENTS}")
        if self.max_retries < 0:
            raise ValueError("سقف المحاولات لا يقل عن صفر")
        if self.timeout_s <= 0:
            raise ValueError("مهلة الوكيل يجب أن تكون موجبة")
        if (type(self.max_tokens) is not int or self.max_tokens <= 0
                or self.max_tokens > 2**63 - 1):
            raise ValueError("max_tokens يجب أن يكون عددًا صحيحًا موجبًا ضمن حد SQLite")

    def system_prompt(self) -> str:
        """مطالبة نظام حتمية من العقد — الدور والأدوات والحدود."""
        tools = ", ".join(sorted(self.tools)) or "لا أدوات"
        return (
            f"[AGENT:{self.role.split(':', 1)[0]}:{self.role.split(':', 1)[1]}]\n"
            f"أنت وكيل في قسم {self.dept} بدور {self.role}. "
            f"أدواتك المسموحة: {tools}. أجب JSON صالحًا فقط."
        )


@dataclass
class MemoryScope:
    """نطاق ذاكرة مهمة — قصير العمر ومقيد بمفاتيح معلنة."""

    mission_id: str
    task_id: str
    allowed_keys: frozenset[str]
    _data: dict[str, Any] = field(default_factory=dict)

    def remember(self, key: str, value: Any, writer: AgentSpec) -> None:
        """كتابة مفتاح معلن — مفتاح خارج عقد الكاتب مرفوض."""
        if key not in writer.memory_keys:
            raise PermissionError(
                f"الوكيل {writer.role} لا يملك مفتاح ذاكرة «{key}» في عقده")
        self._data[key] = value

    def recall(self, key: str, reader: AgentSpec) -> Any:
        """قراءة مفتاح معلن — القارئ خارج عقده يرى لا شيء."""
        if key not in reader.memory_keys:
            return None
        return self._data.get(key)

    def snapshot(self) -> dict[str, Any]:
        return dict(self._data)


@dataclass(frozen=True)
class Tool:
    """أداة واحدة — اسم ووصف ودالة تنفيذ حقيقية."""

    name: str
    description: str
    fn: Callable[..., dict[str, Any]]


class ToolRegistry:
    """سجل الأدوات — كل استدعاء يمر عبر فحص صلاحية العقد."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if not tool.name or not callable(tool.fn):
            raise ValueError("الأداة تحتاج اسمًا ودالة قابلة للاستدعاء")
        self._tools[tool.name] = tool

    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return sorted(self._tools)

    def call(self, spec: AgentSpec, name: str,
             **kwargs: Any) -> dict[str, Any]:
        """استدعاء مُصرَّح — أداة غير مسجلة أو غير مسموحة رفض صريح."""
        tool = self._tools.get(name)
        if tool is None:
            raise ToolDenied(f"أداة غير مسجلة: {name}")
        if name not in spec.tools:
            raise ToolDenied(
                f"الوكيل {spec.role} يطلب «{name}» خارج قائمة أدواته")
        return tool.fn(**kwargs)


@dataclass(frozen=True)
class AgentOutcome:
    """ناتج تشغيل وكيل — نجاح أو فشل مع الاستهلاك والمحاولات."""

    spec_role: str
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    text: str = ""
    attempts: int = 1
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    model_used: str = ""
    provider_used: str = ""
    error: str = ""


class AgentRuntime:
    """وقت التشغيل الموحّد — يستدعي النماذج ويسجل كل محاولة في المتجر."""

    def __init__(self, pool: ProviderPool, tools: ToolRegistry,
                 store: OrgStore) -> None:
        self.pool = pool
        self.tools = tools
        self.store = store

    @staticmethod
    def set_task_lease(task_id: str, claim: dict[str, Any]) -> Token:
        """Bind provider reservations to the current execution context."""
        return _ACTIVE_TASK_LEASE.set({
            "task_id": task_id,
            "attempt_no": int(claim["attempts"]),
            "lease_generation": int(claim["lease_generation"]),
            "lease_owner": str(claim["lease_owner"]),
            "lease_token": str(claim["lease_token"]),
        })

    @staticmethod
    def reset_task_lease(token: Token) -> None:
        """Restore the previous context after a task execution scope."""
        _ACTIVE_TASK_LEASE.reset(token)

    # ── استدعاء النموذج بعقد الوكيل ───────────────────────────────────────

    def complete(self, spec: AgentSpec, user_prompt: str) -> ModelResponse:
        """استدعاء واحد بسلسلة بدائل وسقف محاولات — كل محاولة مسجلة."""
        messages = [
            {"role": "system", "content": spec.system_prompt()},
            {"role": "user", "content": user_prompt},
        ]
        last_error = ""
        for attempt in range(1, spec.max_retries + 2):
            t0 = time.time()
            reservation = self._reserve_output_budget(spec)
            try:
                resp = self.pool.complete_with_fallback(
                    messages, temperature=spec.temperature,
                    max_tokens=spec.max_tokens)
            except ProviderError as exc:
                # A failed provider may have dispatched; charge every fallback ceiling.
                self._settle_output_budget(
                    reservation,
                    spec.max_tokens * self.pool.max_fallback_attempts)
                last_error = str(exc)
                latency = (time.time() - t0) * 1000.0
                self._record(spec, None, attempt, latency, f"error: {last_error}")
                time.sleep(min(0.05 * attempt, 0.3))
                continue
            fallback_charge = len(self.pool.last_errors) * spec.max_tokens
            self._settle_output_budget(
                reservation, fallback_charge + resp.usage.out_tokens)
            latency = (time.time() - t0) * 1000.0
            self._record(spec, resp, attempt, latency, "ok")
            return resp
        raise ProviderError(
            f"الوكيل {spec.role} استنفد محاولاته ({spec.max_retries + 1}): "
            f"{last_error}")

    def ask_json(self, spec: AgentSpec, user_prompt: str) -> AgentOutcome:
        """استدعاء يتوقع JSON — رد غير صالح يعاد حتى السقف ثم فشل صريح."""
        messages = [
            {"role": "system", "content": spec.system_prompt()},
            {"role": "user", "content": user_prompt},
        ]
        last_error = ""
        for attempt in range(1, spec.max_retries + 2):
            t0 = time.time()
            reservation = self._reserve_output_budget(spec)
            try:
                resp = self.pool.complete_with_fallback(
                    messages, temperature=spec.temperature,
                    max_tokens=spec.max_tokens)
            except ProviderError as exc:
                # A failed provider may have dispatched; charge every fallback ceiling.
                self._settle_output_budget(
                    reservation,
                    spec.max_tokens * self.pool.max_fallback_attempts)
                last_error = str(exc)
                self._record(spec, None, attempt,
                             (time.time() - t0) * 1000.0, f"error: {last_error}")
                time.sleep(min(0.05 * attempt, 0.3))
                continue
            fallback_charge = len(self.pool.last_errors) * spec.max_tokens
            self._settle_output_budget(
                reservation, fallback_charge + resp.usage.out_tokens)
            data, parse_error = self._parse_json(resp.text)
            if data is None:
                last_error = parse_error
                self._record(spec, resp, attempt,
                             (time.time() - t0) * 1000.0, f"json: {parse_error}")
                continue
            latency = (time.time() - t0) * 1000.0
            self._record(spec, resp, attempt, latency, "ok")
            return AgentOutcome(
                spec_role=spec.role, success=True, data=data, text=resp.text,
                attempts=attempt, tokens_in=resp.usage.in_tokens,
                tokens_out=resp.usage.out_tokens, cost_usd=resp.usage.cost_usd,
                latency_ms=latency, model_used=resp.model,
                provider_used=resp.provider,
            )
        return AgentOutcome(
            spec_role=spec.role, success=False, attempts=spec.max_retries + 1,
            error=last_error or "رد غير قابل للتحليل",
        )

    @staticmethod
    def _parse_json(text: str) -> tuple[dict[str, Any] | None, str]:
        """تحليل JSON متسامح — أول كائن في النص؛ فشل برسالة صريحة."""
        match = _JSON_OBJ.search(text)
        if not match:
            return None, "لا كائن JSON في الرد"
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            return None, f"JSON غير صالح: {exc}"
        if not isinstance(data, dict):
            return None, "الرد ليس كائنًا"
        return data, ""

    def _reserve_output_budget(self, spec: AgentSpec) -> str | None:
        """Reserve the response-token ceiling when this mission has a budget."""
        budget = self.store.mission_token_budget_get(spec.mission_id)
        if budget is None:
            return None
        lease = _ACTIVE_TASK_LEASE.get()
        reservation = self.store.reserve_mission_output_tokens(
            spec.mission_id, spec.role,
            spec.max_tokens * self.pool.max_fallback_attempts,
            **(lease or {}))
        return str(reservation["id"])

    def _settle_output_budget(self, reservation_id: str | None,
                              actual_tokens: int) -> None:
        """Settle a reservation; an absent budget keeps legacy missions unchanged."""
        if reservation_id is not None:
            self.store.settle_mission_output_tokens(reservation_id, actual_tokens)

    def _record(self, spec: AgentSpec, resp: ModelResponse | None,
                attempt: int, latency_ms: float, status: str) -> None:
        """سجل تشغيل واحد في المتجر — بلا استثناءات تُسقط المهمة."""
        tokens_in = resp.usage.in_tokens if resp else 0
        tokens_out = resp.usage.out_tokens if resp else 0
        cost = resp.usage.cost_usd if resp else 0.0
        try:
            self.store.add_agent_run(
                mission_id=spec.mission_id, task_id=spec.task_id,
                role=spec.role,
                provider=(resp.provider if resp else self.pool.get().name),
                model=(resp.model if resp else ",".join(spec.models or ["default"])),
                status=status, attempts=attempt, tokens_in=tokens_in,
                tokens_out=tokens_out, cost_usd=cost, latency_ms=latency_ms,
            )
        except Exception:  # noqa: BLE001 — السجل لا يُسقط المهمة
            pass

    # ── الأدوات باسم الوكيل ───────────────────────────────────────────────

    def use_tool(self, spec: AgentSpec, name: str,
                 **kwargs: Any) -> dict[str, Any]:
        """أداة مُصرَّح باسم الوكيل — فحص العقد قبل التنفيذ."""
        return self.tools.call(spec, name, **kwargs)
