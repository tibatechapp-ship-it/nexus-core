"""مُكيّفات مزوّدي النماذج — طبقة واحدة خلفها كل الوكلاء.

القواعد المعلنة:

* **مفتاح واحد لكل الوكلاء**: الوكيل لا يعرف أي مزوّد يخدمه — يرسل
  رسائل ويستقبل نصًا واستهلاكًا. تبديل المزوّد لا يعدّل وكيلًا واحدًا.
* **مزوّدان حقيقيان**:
  - ``MockProvider``: بدلة اختبار حتمية بلا شبكة — نفس المُدخل يعطي
    نفس المُخرج في كل تشغيل، وهو ما يجعل الاختبارات والعرض الشامل
    قابلين لإعادة الإنتاج دون مفاتيح أو اتصال.
  - ``OpenAICompatProvider``: مُكيّف عام لأي نقطة نهاية متوافقة مع
    ``/chat/completions`` عبر ``urllib`` القياسي — بلا اعتماديات خارجية.
* **سلسلة بدائل (fallback)**: ``ProviderPool`` يجرب النماذج بالترتيب على
  ``ProviderError`` — فشل مزوّد لا يُسقط المهمة قبل استنفاد السلسلة.
* **حساب الاستهلاك إلزامي**: كل رد يحمل توكنات وكلفة تقديرية من جدول
  أسعار معلن — الكلفة صفر للمزوّد المحلي أو غير المدرج، لا تخمين.

لا يُكتب أي مفتاح API في السجلات ولا في الاستثناءات — الرسائل تحمل
أسماء المزوّدين والنماذج فقط.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "PRICE_TABLE",
    "ModelResponse",
    "OpenAICompatProvider",
    "Provider",
    "ProviderConfig",
    "ProviderError",
    "ProviderPool",
    "Usage",
    "estimate_cost",
]


@dataclass(frozen=True)
class ProviderConfig:
    """إعداد مزوّد واحد — الاسم والنموذج ونقطة النهاية والمفتاح."""

    name: str = "mock"
    model: str = "mock-1"
    base_url: str = ""
    api_key: str = ""
    timeout_s: float = 120.0


@dataclass(frozen=True)
class Usage:
    """استهلاك استدعاء واحد — توكنات وكلفة تقديرية."""

    in_tokens: int = 0
    out_tokens: int = 0
    cost_usd: float = 0.0


@dataclass(frozen=True)
class ModelResponse:
    """رد نموذج واحد — النص والاستهلاك وزمن الاستجابة."""

    text: str
    provider: str
    model: str
    usage: Usage
    latency_ms: float
    finish_reason: str = "stop"


class ProviderError(RuntimeError):
    """فشل استدعاء مزوّد — بلا تفاصيل مفاتيح، أسماء ونماذج فقط."""


#: أسعار تقديرية بالدولار لكل مليون توكن — للحساب فقط، لا للفوترة.
PRICE_TABLE: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "claude-3-5-haiku": (0.80, 4.00),
    "claude-3-5-sonnet": (3.00, 15.00),
    "deepseek-chat": (0.14, 0.28),
    "llama-3.1-8b": (0.05, 0.05),
    "mock-1": (0.0, 0.0),
    "": (0.0, 0.0),
}


def estimate_cost(model: str, usage: Usage) -> float:
    """كلفة تقديرية من جدول معلن — نموذج غير مدرج = صفر (لا تخمين)."""
    in_price, out_price = PRICE_TABLE.get(model, (0.0, 0.0))
    return (usage.in_tokens / 1_000_000) * in_price \
        + (usage.out_tokens / 1_000_000) * out_price


class Provider:
    """الأساس المجرد — عقد واحد لكل المزوّدين."""

    name: str = ""
    model: str = ""

    def complete(self, messages: list[dict[str, str]], *,
                 temperature: float = 0.2,
                 max_tokens: int = 2000) -> ModelResponse:
        raise NotImplementedError

    def __repr__(self) -> str:  # pragma: no cover — تمثيل قرائي فقط
        return f"<Provider {self.name}/{self.model}>"


# ── المزوّد المتوافق مع OpenAI ────────────────────────────────────────────


class OpenAICompatProvider(Provider):
    """مُكيّف عام لنقاط نهاية /chat/completions — urllib قياسي بلا اعتماديات.

    أي مزوّد يلتزم الشكل المعلن يعمل هنا: OpenAI أو vLLM أو Ollama (وضع
    openai) أو غيرها. الفشل شبكي/بروتوكولي يُرفع ``ProviderError`` رسالته
    بلا مفاتيح ولا رؤوس تفويض.
    """

    def __init__(self, cfg: ProviderConfig) -> None:
        if not cfg.base_url:
            raise ProviderError("مزوّد حقيقي يحتاج base_url معلنًا")
        try:
            parsed = urlsplit(cfg.base_url)
            valid_url = (
                parsed.scheme in {"http", "https"}
                and bool(parsed.hostname)
                and parsed.username is None
                and parsed.password is None
            )
            _ = parsed.port
        except ValueError:
            valid_url = False
        if not valid_url:
            raise ProviderError("base_url must be a valid HTTP(S) URL without userinfo")
        self.cfg = cfg
        self.name = cfg.name
        self.model = cfg.model
        self._base = cfg.base_url.rstrip("/")

    def complete(self, messages: list[dict[str, str]], *,
                 temperature: float = 0.2,
                 max_tokens: int = 2000) -> ModelResponse:
        url = f"{self._base}/chat/completions"
        body = json.dumps({
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"
        req = urllib.request.Request(url, data=body, headers=headers,
                                     method="POST")
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.cfg.timeout_s) as resp:  # nosec B310 — base_url validated as HTTP(S)
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ProviderError(
                f"فشل مزوّد {self.name}/{self.model}: {type(exc).__name__}") from exc
        latency = (time.time() - t0) * 1000.0
        choices = data.get("choices") or [{}]
        text = (choices[0].get("message") or {}).get("content", "")
        usage_raw = data.get("usage") or {}
        usage = Usage(
            in_tokens=int(usage_raw.get("prompt_tokens", 0)),
            out_tokens=int(usage_raw.get("completion_tokens", 0)),
        )
        usage_cost = estimate_cost(self.model, usage)
        return ModelResponse(
            text=text, provider=self.name, model=self.model,
            usage=Usage(usage.in_tokens, usage.out_tokens, usage_cost),
            latency_ms=latency,
            finish_reason=choices[0].get("finish_reason", "stop"),
        )


# ── المزوّد الحتمي للاختبار ───────────────────────────────────────────────

_AGENT_TAG = re.compile(r"\[AGENT:([a-z_:]+)\]")
_FILE_LINE = re.compile(r"^file:\s*(\S+)", re.MULTILINE)


def _deterministic_hash(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)


class MockProvider(Provider):
    """بدلة اختبار حتمية — بلا شبكة وبلا مفاتيح وقابلية إعادة إنتاج كاملة.

    تعمل بقراءة وسم الدور ``[AGENT:role]`` المُدرج في المطالبة ثم بناء
    رد JSON صالح البنية من محتوى المطالبة نفسها (ملفات هدف، معايير قبول،
    خرائط مستودع). تُستخدم للاختبارات والعرض الشامل دون اتصال؛ الإنتاج
    يستخدم ``OpenAICompatProvider`` أو أي مُكيّف مستقبلي بنفس العقد.
    """

    def __init__(self, cfg: ProviderConfig | None = None) -> None:
        self.cfg = cfg or ProviderConfig(name="mock", model="mock-1")
        self.name = self.cfg.name or "mock"
        self.model = self.cfg.model or "mock-1"

    def complete(self, messages: list[dict[str, str]], *,
                 temperature: float = 0.2,
                 max_tokens: int = 2000) -> ModelResponse:
        prompt = messages[-1]["content"] if messages else ""
        # وسم الدور في رسالة النظام — يُبحث في كل الرسائل لا الأخيرة فقط
        tag_source = "\n".join(m.get("content", "") for m in messages)
        tag_match = _AGENT_TAG.search(tag_source)
        tag = tag_match.group(1) if tag_match else "generic"
        t0 = time.time()
        text = self._reply(tag, prompt)
        latency = (time.time() - t0) * 1000.0
        usage = Usage(in_tokens=max(1, len(prompt.split())),
                      out_tokens=max(1, len(text.split())), cost_usd=0.0)
        return ModelResponse(text=text, provider=self.name, model=self.model,
                             usage=usage, latency_ms=latency)

    # ── بناء الردود حسب الدور ─────────────────────────────────────────────

    def _reply(self, tag: str, prompt: str) -> str:
        # التصنيف ببادئة الدور — "requirements:analyst" يعمل كـ"requirements"
        if tag.startswith("requirements"):
            return self._requirements_reply(prompt)
        if tag.startswith("repo_intel"):
            return self._repo_intel_reply(prompt)
        if tag.startswith("dev"):
            return self._dev_reply(prompt)
        if tag.startswith("review"):
            return self._review_reply(prompt, tag)
        if tag.startswith("qa"):
            return self._qa_reply(prompt)
        if tag.startswith("security"):
            return self._security_reply(prompt)
        if tag.startswith("verification"):
            return self._verification_reply(prompt)
        if tag.startswith("release"):
            return self._release_reply(prompt)
        return json.dumps({"status": "ok", "note": "رد حتمي عام"},
                          ensure_ascii=False)

    def _requirements_reply(self, prompt: str) -> str:
        """معايير قبول مستخرجة حتميًا من الهدف المُدرج في المطالبة."""
        match = re.search(r"OBJECTIVE:\s*(.+)", prompt)
        objective = match.group(1).strip() if match else prompt.strip()
        h = _deterministic_hash(objective)
        verbs = []
        for kw, crit in (
            ("divid", "قسمة بصفر تُرفض برسالة صريحة"),
            ("valid", "مدخلات غير صالحة تُرفض دون استثناء خام"),
            ("test", "اختبارات تغطي الحالات الحدية"),
            ("auth", "مسارات بلا تصريح تُرفض"),
            ("api", "نقطة النهاية تعيد 400 لمدخلات سيئة"),
        ):
            if kw in objective.lower():
                verbs.append(crit)
        if not verbs:
            verbs = [f"سلوك الهدف موثّق بمعيار قابل للقياس #{h % 3 + 1}"]
        ambiguities = []
        if "?" in objective:
            ambiguities.append("الهدف صيغ كسؤال — يحتاج تثبيت نطاق")
        return json.dumps({
            "acceptance_criteria": verbs,
            "constraints": ["لا تغييرات خارج الملفات المتأثرة"],
            "ambiguities": ambiguities,
        }, ensure_ascii=False)

    def _repo_intel_reply(self, prompt: str) -> str:
        files = _FILE_LINE.findall(prompt)
        return json.dumps({
            "architecture_summary": (
                f"حزمة Python بمكوّنات {len(files)} ملفًا معلنًا في الخريطة."),
            "suggested_focus": files[:3],
            "notes": "ملخص ذكاء المستودع الحتمي.",
        }, ensure_ascii=False)

    def _dev_reply(self, prompt: str) -> str:
        """رقعة تطوير حتمية للملفات المُعلنة في قسم TARGET FILES."""
        files = _FILE_LINE.findall(prompt)
        fn_match = re.search(r"FUNCTION:\s*(\w+)", prompt)
        fn_name = fn_match.group(1) if fn_match else "target_op"
        guard_desc = re.search(r"GUARD:\s*(.+)", prompt)
        guard = guard_desc.group(1).strip() if guard_desc else "مدخلات غير صالحة"
        changed: list[dict[str, str]] = []
        if files:
            path = files[0]
            content = (
                f"def {fn_name}(value, divisor):\n"
                f"    \"\"\"{fn_name}: تنفيذ مُحدَّث وفق متطلبات المهمة.\n\n"
                f"    يرفض {guard} برسالة صريحة قبل أي حساب.\n"
                f"    \"\"\"\n"
                f"    if divisor == 0:\n"
                f"        raise ValueError(\"القاسم صفر غير مسموح\")\n"
                f"    return value / divisor\n"
            )
            changed.append({"path": path, "content": content})
        if len(files) > 1:
            tests = files[1]
            test_content = (
                f"import pytest\n\n"
                f"from {'.'.join(files[0].replace('.py', '').split('/'))} "
                f"import {fn_name}\n\n\n"
                f"def test_{fn_name}_normal():\n"
                f"    assert {fn_name}(10, 2) == 5\n\n\n"
                f"def test_{fn_name}_zero_guard():\n"
                f"    with pytest.raises(ValueError):\n"
                f"        {fn_name}(1, 0)\n"
            )
            changed.append({"path": tests, "content": test_content})
        return json.dumps({
            "changed_files": changed,
            "notes": f"تطبيق {fn_name} مع حارس صريح واختبارات.",
            "risks": [{"severity": "low",
                       "message": "رقعة عرض حتمية — تُراجع مستقلًا"}],
        }, ensure_ascii=False)

    def _review_reply(self, prompt: str, tag: str) -> str:
        """مراجعة حتمية: الدرجة من بصمة المطالبة + فحوص ساكنة حقيقية."""
        lens = tag.split(":", 1)[1] if ":" in tag else "logic"
        h = _deterministic_hash(f"{lens}\n{prompt}")
        score = 72 + (h % 28)
        issues: list[dict[str, Any]] = []
        # فحص حقيقي لا مزيف: مطالبة المراجعة تحمل نص الرقعة داخل قسم DIFF.
        diff_section = re.search(r"DIFF:\n(.*?)(?:\n\n|$)", prompt, re.DOTALL)
        if diff_section:
            diff_text = diff_section.group(1)
            if "except:" in diff_text and "except Exception" not in diff_text:
                issues.append({
                    "severity": "high", "file": "", "line": 0,
                    "message": "استثناء عارٍ بلا نوع — التقط أخطاء برمجية بالخطأ",
                })
            if re.search(r"\beval\s*\(", diff_text) \
                    or re.search(r"\bexec\s*\(", diff_text):
                issues.append({
                    "severity": "critical", "file": "", "line": 0,
                    "message": "تنفيذ ديناميكي (eval/exec) في رقعة — ممنوع",
                })
            if "TODO" in diff_text:
                issues.append({
                    "severity": "low", "file": "", "line": 0,
                    "message": "TODO متبقٍ في الرقعة",
                })
        if issues:
            score = min(score, 70)
        verdict = "approve" if score >= 80 and not issues else "request_changes"
        return json.dumps({
            "verdict": verdict, "score": score, "issues": issues,
            "reasoning": f"مراجعة حتمية بعدسة {lens} قابلة لإعادة الإنتاج.",
        }, ensure_ascii=False)

    def _qa_reply(self, prompt: str) -> str:
        files = _FILE_LINE.findall(prompt)
        return json.dumps({
            "test_plan": [
                {"name": "حالات طبيعية", "target": files[0] if files else ""},
                {"name": "حالات حدية", "target": files[1] if len(files) > 1 else ""},
            ],
            "notes": "خطة اختبار حتمية من قائمة الملفات.",
        }, ensure_ascii=False)

    def _security_reply(self, prompt: str) -> str:
        return json.dumps({
            "threat_notes": ["لا تمدد صلاحيات في الرقعة"],
            "notes": "ملخص أمني حتمي — الفحوص الساكنة أصلًا كود حقيقي.",
        }, ensure_ascii=False)

    def _verification_reply(self, prompt: str) -> str:
        h = _deterministic_hash(prompt)
        return json.dumps({
            "assessment": "الأدلة المرفقة كافية للتحقق" if h % 2 == 0
            else "الأدلة المرفقة تحتاج إعادة تشغيل مستقلة",
            "notes": "رأي تحقق حتمي — القرار النهائي لمحرك الأدلة.",
        }, ensure_ascii=False)

    def _release_reply(self, prompt: str) -> str:
        return json.dumps({
            "pr_title": "تحديث مُراجع مع اختبارات وأدلة",
            "pr_body_sections": ["ما تغيّر", "لماذا", "المخاطر", "الاختبارات",
                                 "التراجع"],
            "notes": "هيكل طلب سحب حتمي — الدمج بشرية دائمًا.",
        }, ensure_ascii=False)


# ── الحوض مع سلسلة البدائل ────────────────────────────────────────────────


class ProviderPool:
    """حوض مزوّدين مع سلسلة بدائل وحساب استهلاك موحّد.

    ``cfgs`` قائمة إعدادات بالترتيب المعلن؛ ``complete_with_fallback``
    يجربها واحدًا بعد الآخر على ``ProviderError`` — كل محاولة تسجَّل
    في ``last_errors`` لشريحة التدقيق.
    """

    def __init__(self, cfgs: list[ProviderConfig] | None = None) -> None:
        self._cfgs = cfgs or [ProviderConfig(name="mock", model="mock-1")]
        self._cache: dict[str, Provider] = {}
        self.last_errors: list[str] = []

    def get(self, name: str = "", model: str = "") -> Provider:
        for cfg in self._cfgs:
            if cfg.name == (name or self._cfgs[0].name):
                key = f"{cfg.name}:{model or cfg.model}"
                if key not in self._cache:
                    chosen = ProviderConfig(
                        name=cfg.name, model=model or cfg.model,
                        base_url=cfg.base_url, api_key=cfg.api_key,
                        timeout_s=cfg.timeout_s,
                    )
                    if chosen.name == "mock":
                        self._cache[key] = MockProvider(chosen)
                    else:
                        self._cache[key] = OpenAICompatProvider(chosen)
                return self._cache[key]
        raise ProviderError(f"مزوّد غير معلن في الحوض: {name or 'افتراضي'}")

    @property
    def max_fallback_attempts(self) -> int:
        """Maximum provider dispatches one logical completion may perform."""
        return len(self._cfgs)

    def models(self) -> list[str]:
        """سلسلة النماذج المعلنة بالترتيب — أولها الافتراضي."""
        return [cfg.model for cfg in self._cfgs]

    def complete_with_fallback(self, messages: list[dict[str, str]], *,
                               temperature: float = 0.2,
                               max_tokens: int = 2000) -> ModelResponse:
        """تجربة السلسلة بالترتيب — فشل كلها يرفع بخلاصة الأخطاء."""
        self.last_errors = []
        for cfg in self._cfgs:
            try:
                return self.get(cfg.name, cfg.model).complete(
                    messages, temperature=temperature, max_tokens=max_tokens)
            except ProviderError as exc:
                self.last_errors.append(str(exc))
                continue
        raise ProviderError("سلسلة النماذج استُنفدت: " + " | ".join(self.last_errors))


def default_pool() -> ProviderPool:
    """الحوض الافتراضي — حتمي محلي بلا شبكة ولا مفاتيح."""
    return ProviderPool([ProviderConfig(name="mock", model="mock-1")])


def pool_from_env_vars(env: dict[str, str] | None = None) -> ProviderPool:
    """حوض من متغيرات بيئة معلنة (اختياري) — بلا مفاتيح في الكود."""
    import os
    src = env if env is not None else dict(os.environ)
    cfgs: list[ProviderConfig] = []
    base_url = src.get("ORG_LLM_BASE_URL", "")
    api_key = src.get("ORG_LLM_API_KEY", "")
    model = src.get("ORG_LLM_MODEL", "")
    if base_url and model:
        cfgs.append(ProviderConfig(name="openai-compat", model=model,
                                   base_url=base_url, api_key=api_key))
    cfgs.append(ProviderConfig(name="mock", model="mock-1"))
    return ProviderPool(cfgs)
