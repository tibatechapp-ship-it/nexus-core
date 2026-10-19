"""Monkey-patch LLMRouter to add monitoring automatically."""
from __future__ import annotations
from typing import Any
import time
import functools


_patched = False

#: علامة توضع على الغلاف كي نتعرّف عليه لاحقًا (أدقّ من فحص __wrapped__).
_MARKER = "_nexus_monitored"


def _is_wrapped(generate: Any) -> bool:
    """هل الدالة الحالية غلاف المراقبة؟ (idempotency by inspection)."""
    return getattr(generate, _MARKER, False) is True


def patch_llm_router() -> Any:
    """يلفّ LLMRouter.generate() ليتتبع الاستدعاءات.

    idempotent *بالفحص* لا بالعلم فقط: لا يكفي متغيّر ``_patched`` لأن
    ``importlib.reload(novamind.core.llm_router)`` يُنشئ صنف ``LLMRouter``
    جديدًا لم يُلفّ بعد بينما يبقى ``_patched`` على True → كانت إعادة التسلّح
    تفشل صامتة. لذا نفحص دالة ``generate`` الحالية ونلفّها إن لم تكن مُلفّفة.
    """
    global _patched

    try:
        from novamind.core.llm_router import LLMRouter
        from src.nexus.monitoring import get_monitor
    except ImportError as e:
        print(f"⚠️ Patch فشل: {e}")
        return False

    current = LLMRouter.generate
    if _is_wrapped(current):
        _patched = True
        return True

    original_generate = current

    @functools.wraps(original_generate)
    def monitored_generate(self: Any, prompt: Any ="", system: Any ="", provider: Any =None, **kwargs: Any) -> Any:
        _t0 = time.time()
        mon = get_monitor()

        try:
            result = original_generate(self, prompt=prompt, system=system,
                                        provider=provider, **kwargs)

            # استخرج المزود من النتيجة
            provider_name = "unknown"
            model = "unknown"
            text = ""
            if isinstance(result, dict):
                provider_name = result.get("provider", "unknown") or "unknown"
                model = result.get("model", "unknown") or "unknown"
                text = result.get("text", "") or ""

            # سجّل
            try:
                mon.log_call(
                    provider=provider_name,
                    model=model,
                    elapsed=time.time() - _t0,
                    ok=bool(result.get("ok", False)) if isinstance(result, dict) else True,
                    prompt=prompt + " " + (system or ""),
                    response=text,
                )
            except Exception:
                pass

            return result

        except Exception as e:
            try:
                mon.log_call(
                    provider=provider or "unknown",
                    model="unknown",
                    elapsed=time.time() - _t0,
                    ok=False,
                    prompt=prompt,
                    error=str(e)[:200],
                )
            except Exception:
                pass
            raise

    setattr(monitored_generate, _MARKER, True)
    LLMRouter.generate = monitored_generate
    _patched = True
    return True


# ═══ طبّق عند الاستيراد ═══
patch_llm_router()
