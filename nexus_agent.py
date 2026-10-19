#!/usr/bin/env python3
"""nexus_agent.py — Nexus-Core Unified Server (v1.13)
=====================================================

خادم FastAPI **واحد** يلفّ طبقات المشروع الثلاث دون فقدان أي ميزة
(*gradual unification with separation* — توحيد تدريجي مع فصل):

1. **Workbench** — يُستورَد ``main.py`` بالكامل ويُعاد استخدام تطبيقه كما هو،
   فتبقى كل مساراته محفوظة: ``/api/deliberate`` (SSE)، ``/api/build``،
   ``/api/builds``، ``/api/craft`` (حقيقي)، ``/api/history`` (+بحث)،
   ``/api/topics``، ``/api/stats``، ``/api/review``، PWA، وSwagger.
2. **Engine** — ``unified_agent.py`` (محرّك novamind: محادثة + Time Machine
   + ``/api/conversations`` + ``/api/traces`` + pipeline + offline) يُثبَّت
   كـ **catch-all** في آخر السطور: مسارات الوورك‌بنش وأعمالي أعلاه تفوز،
   والمحرّك يلتقط ما تبقّى (43 مساراً).
3. **NovaMind Living Council** (5 أعضاء + Genome) — يُضاف فوق **نفس** التطبيق:
   ``/api/council/{debate,stream,sessions}`` + ``/api/genome*``.
4. **Framework agents** (20) — ``/api/agents``، مع ``/api/status`` الموحّد
   و``/api/chat`` (LLM حقيقي عبر ``LLMRouter``).

التشغيل::

    PYTHONPATH=src:. python3 nexus_agent.py        # NEXUS_PORT (افتراضي 8080)

الخادم واحد — لكن الطبقات تبقى منفصلة وقابلة للاختبار كلٌّ بمفرده.

ملاحظة: بلا ``from __future__ import annotations`` (مثل main.py) لأن نماذج
Pydantic تحتاج أنواعاً حقيقية عند التعريف — يجعله محصّناً ضدّ أي طريقة تحميل.
"""

import asyncio
import fcntl
import importlib.util
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

from fastapi import HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    StreamingResponse,
)
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent
for _p in (str(BASE_DIR), str(BASE_DIR / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# `tools/` تحمل وحدات مسطّحة (exec_sandbox، ollama_router…) تُستورَد بأسمائها
# المجرّدة لا كـ`tools.<name>` — فتحتاج المجلد نفسه على المسار. أُضيف في الذيل
# (لا الرأس) حتّى لا تُزاحم أسبقية جذر المستودع عند أي تشابه أسماء.
if str(BASE_DIR / "tools") not in sys.path:
    sys.path.append(str(BASE_DIR / "tools"))


# ═══════════════════════════════════════════════════════════════════════
# 1) Workbench (main.py) — يُحمَّل بالمسار تحت اسم خاص (`_nexus_workbench`)
#    تفادياً لتضارب اسم `main`: novamind يضيف src/novamind إلى المسار فيوجد
#    هناك main.py آخر، وbare `import main` قد يلتقطه.
# ═══════════════════════════════════════════════════════════════════════
def _load_workbench() -> Any:
    """حمّل main.py بالمسار وأعد وحدته (تشغيل كودها العلوي: sys.path + .env)."""
    spec = importlib.util.spec_from_file_location(
        "_nexus_workbench", BASE_DIR / "main.py")
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError("تعذّر تحميل main.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_nexus_workbench"] = mod
    spec.loader.exec_module(mod)
    return mod


_wb = _load_workbench()
app = _wb.app  # ← نفس تطبيق الوورك‌بنش: خادم واحد وكل مساراته محفوظة


# ── NovaMind (المجلس الحيّ + Genome) — بعد ضبط المسار ──────────────────
COUNCIL_OK = False
COUNCIL_ERR = ""
try:
    from novamind.council import COUNCIL_MEMBERS, Council  # noqa: E402
    from novamind.core.llm_router import LLMRouter  # noqa: E402
    from novamind.core.session_store import get_store  # noqa: E402
    from novamind.genome import Genome  # noqa: E402
    COUNCIL_OK = True
except Exception as _e:  # pragma: no cover - defensive
    COUNCIL_ERR = f"{type(_e).__name__}: {_e}"


# ── Engine (unified_agent.py) — محرّك novamind الكامل (محادثة + Time
#    Machine + PWA) يُحمَّل بالمسار أيضاً ويُلفّ كـ catch-all ──────────────
def _load_engine() -> Any:
    """حمّل unified_agent.py بالمسار تحت اسم خاص (لا تضارب اسم ``app``)."""
    spec = importlib.util.spec_from_file_location(
        "_nexus_engine", BASE_DIR / "unified_agent.py")
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError("تعذّر تحميل unified_agent.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_nexus_engine"] = mod  # Pydantic تحلّج __module__ هنا
    spec.loader.exec_module(mod)
    return mod


ENGINE_OK = False
ENGINE_ERR = ""
_engine: Any = None
try:
    _engine = _load_engine()
    ENGINE_OK = True
except Exception as _e:  # pragma: no cover - defensive
    ENGINE_ERR = f"{type(_e).__name__}: {_e}"


# ═══════════════════════════════════════════════════════════════════════
# Singletons — كسولة: لا تفتح قاعدة البيانات ولا تحمّل المزودين قبل الحاجة
# ═══════════════════════════════════════════════════════════════════════
_store: Any = None
_genome: Any = None
_council: Any = None
_router: Any = None


def get_store_singleton() -> Any:
    """مخزن الجلسات/الجينوم المشترك (process-wide singleton)."""
    global _store
    if _store is None:
        _store = get_store()
    return _store


def get_genome() -> Any:
    """جينوم الوكلاء، مبذور من أدوار المجلس عند أول استخدام."""
    global _genome
    if _genome is None:
        _genome = Genome(get_store_singleton())
        _genome.seed(members=COUNCIL_MEMBERS)
    return _genome


def get_router() -> Any:
    """موجّه LLM من طبقة novamind (يقرأ المزودين من ``NOVAMIND_HOME/.env``)."""
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router


def get_council() -> Any:
    """المجلس الحيّ المشترك (router + store + genome)."""
    global _council
    if _council is None:
        _council = Council(router=get_router(), store=get_store_singleton(),
                           genome=get_genome())
    return _council


# ═══════════════════════════════════════════════════════════════════════
# H1) حارس الوصول — طبقة أمنية واحدة: token + حدّ معدّل + سجل تدقيق
#   • المصادقة    : ``NEXUS_AUTH_TOKEN`` (فارغ ⇒ معطّلة) والرأس ``X-Auth-Token``
#   • حدّ المعدّل : ``NEXUS_RATE_LIMIT`` / ``NEXUS_RATE_WINDOW`` (افتراضي 120/60s)
#   • سجل التدقيق : ``NEXUS_AUDIT_LOG`` (مسار ملف JSONL، أو off ⇒ معطّل)
#   يُركَّب كـ HTTP middleware **واحد** فيغطّي الطبقات الثلاث معاً (وورك‌بنش +
#   مساراتي + المحرّك المثبَّت catch-all) دون لمس أي مسار، والمحميّ هو الطرق
#   المتغيّرة فقط (POST/PUT/PATCH/DELETE)؛ القراءات تمرّ دائماً.
# ═══════════════════════════════════════════════════════════════════════
try:
    from src.security.access import AccessGuard

    GUARD: Any = AccessGuard.from_env()
    GUARD_ERR = ""
except Exception as _e:  # pragma: no cover - defensive
    GUARD = None
    GUARD_ERR = f"{type(_e).__name__}: {_e}"


if GUARD is not None:
    @app.middleware("http")
    async def _access_guard(request: Request,
                            call_next: Callable[[Any], Any]) -> Any:
        """بوّابة واحدة لكل الطلبات: فحص ⇒ مرور ⇒ تسجيل."""
        client = request.client.host if request.client else None
        decision = GUARD.check(request.method, request.url.path,
                               request.headers, client)
        if decision.allowed:
            response = await call_next(request)
        else:
            payload: Dict[str, Any] = {"ok": False, "error": decision.error}
            if decision.retry_after:
                payload["retry_after"] = decision.retry_after
            response = JSONResponse(payload, status_code=decision.status)
            if decision.retry_after:
                # سقفٌ لا أرضٌ: العميل ينتظر ما يكفي (ceil) لا أقلّ
                response.headers["Retry-After"] = str(
                    max(1, math.ceil(decision.retry_after)))
        GUARD.record(decision, request.method, request.url.path, client=client,
                     status=response.status_code)
        return response


# ═══════════════════════════════════════════════════════════════════════
# المراقبة (src/nexus) — تتبّع استدعاءات LLM: التوكن، الزمن، التكلفة
# ═══════════════════════════════════════════════════════════════════════
# الطبقة كانت مكتملة ومُختبَرة لكن **غير موصولة**: لا شيء يستوردها في الخدمة،
# فلا يُسجَّل أيّ استدعاء. استيراد ``src.nexus`` يُسلّح تلقائياً لفَّ
# ``LLMRouter.generate`` (عبر ``monitoring_patch``) فيُسجَّل كل استدعاء حقيقي.
# أيّ فشل استيراد يُعطّل هذه الطبقة فقط ولا يكسر الخدمة (نمط التدهور ذاته).
MONITORING_OK = False
MONITORING_ERR = ""
_nexus_get_monitor: Optional[Callable[[], Any]] = None
try:
    from src.nexus.monitoring import get_monitor as _nexus_get_monitor

    # أعِد التسلّح صريحًا (self-healing): لو كان ``src.nexus`` مُستوردًا سابقًا
    # فلا يُعاد تشغيل جسم الوحدة عند هذا الاستيراد، ولو أُعيد تحميل
    # ``novamind.core.llm_router`` بعد التسلّح الأول لضاع اللفّ. نداء صريح
    # يلفّ الصنف الحالي (idempotent بالفحص) فيبقى التتبّع فعّالًا دائمًا.
    from src.nexus.monitoring_patch import patch_llm_router as _rearm_monitoring

    _rearm_monitoring()
    MONITORING_OK = True
except Exception as _mon_e:  # pragma: no cover - defensive
    MONITORING_ERR = f"{type(_mon_e).__name__}: {_mon_e}"


# ═══════════════════════════════════════════════════════════════════════
# Models + helpers
# ═══════════════════════════════════════════════════════════════════════
class ChatRequest(BaseModel):
    message: str
    conversation_id: str = "default"
    agent: Optional[str] = None


class CouncilRequest(BaseModel):
    topic: str
    rounds: int = 2


class GenomePatch(BaseModel):
    name: Optional[str] = None
    persona: Optional[str] = None


def _sse(payload: Any) -> str:
    """صيغة SSE يدوية: ``data: <json>\\n\\n`` (أو نص خام مثل ``[DONE]``)."""
    if isinstance(payload, str):
        return f"data: {payload}\n\n"
    return "data: " + json.dumps(payload, ensure_ascii=False, default=str) + "\n\n"


def _clamp_rounds(value: Any, default: int = 2) -> int:
    try:
        return max(1, min(int(value or default), 5))
    except (TypeError, ValueError):
        return default


def _agent_classes() -> List[Any]:
    """فئات الوكلاء العشرين المدمجين (فارغة لو تعذّر الاستيراد)."""
    try:
        from src.agents import AGENT_CLASSES
        return list(AGENT_CLASSES)
    except Exception:
        return []


_DEFAULT_SYSTEM = "أنت مساعد Nexus-Core. أجب بدقّة وبإيجاز، بالعربية إن سُئلت بالعربية."


def _agent_for(agent_id: Optional[str]) -> Optional[Any]:
    """فئة الوكيل بالاسم، أو ``None`` (معرّف فاضٍ/غير معروف/تعذّر الاستيراد)."""
    if not agent_id:
        return None
    for cls in _agent_classes():
        if getattr(cls, "name", "") == agent_id:
            return cls
    return None


def _agent_system(agent_id: Optional[str], task: str = "") -> str:
    """نصّ نظام الوكيل، مدعومًا بقاعدة المعرفة (الطبقة 2) والمهارات (الطبقة 3)
    وذاكرة الميدان (الطبقة 4، المرحلة 1).

    يُحقَن قبل نداء LLM: قاعدة المعرفة تضيف سياق المشروع (بوابات/أعراف/وثيقة
    الفئة)، ثم المهارات تضيف إجراءات الوكيل المُفعَّلة (من بيانه: مراجعة كود،
    اختبار، تدقيق أمني…)، ثم ذاكرة الميدان تعيد تجارب دردشة سابقة مشابهة —
    فتصبح الإجابة على دراية بالمشروع وبمنهج الوكيل وبما جرى فعلاً.
    ``include_task=False`` لأن المهمّة هي دور المستخدم نفسه في الدردشة (تُستعمل
    للترجيح لا تُنسَخ في نصّ النظام). تعذّر أي طبقة يُبقي البرومبت الأساسي —
    لا يكسر الدردشة أبداً.
    """
    cls = _agent_for(agent_id)
    if cls is not None:
        fallback = getattr(cls, "system_prompt", "") or _DEFAULT_SYSTEM
        identity: Any = cls
    else:
        fallback = _DEFAULT_SYSTEM
        identity = agent_id or "default"
    try:
        from src.knowledge import inject_into_prompt

        composed = inject_into_prompt(
            identity, task, include_task=False, instructions=fallback
        )
    except Exception:  # pragma: no cover - defensive: never break chat
        composed = fallback
    try:
        from src.skills import inject_skills_into_prompt

        composed = inject_skills_into_prompt(composed, identity)
    except Exception:  # pragma: no cover - defensive: never break chat
        pass
    try:
        memories = _memory_block(task)
    except Exception:  # pragma: no cover - defensive: never break chat
        memories = ""
    return composed + (f"\n\n{memories}" if memories else "")


# ═══════════════════════════════════════════════════════════════════════
# /api/status — الحالة الموحّدة (كل الطبقات في مكان واحد)
# ═══════════════════════════════════════════════════════════════════════
def _topic_count() -> int:
    """عدد مواضيع الوورك‌بنش — من مخزن المواضيع الحقيقي لا رقم مكتوب يدوياً."""
    try:
        from src.council.topics import TOPICS
        return len(TOPICS)
    except Exception:
        return 0


def _novamind_agent_count() -> int:
    """عدد وحدات وكلاء novamind — عدّ ملفات (بلا استيراد ثقيل)."""
    try:
        root = BASE_DIR / "src" / "novamind" / "agents"
        return len([p for p in root.glob("*.py") if p.name != "__init__.py"])
    except Exception:
        return 0


@app.get("/api/status")
def api_status() -> Dict[str, Any]:
    """حالة الخادم الموحّد: مكوّنات الطبقات الثلاث.

    عقد يستهلكه ``scripts/bin/nexus`` (``agents`` مفكّك + ``engine`` +
    ``topics``) — شكله الفرعي ``components`` لازم يبقى قاموساً.
    """
    framework = len(_agent_classes())
    novamind = _novamind_agent_count()
    guard_stats: Dict[str, Any] = (
        GUARD.stats() if GUARD is not None else {"error": GUARD_ERR or "disabled"}
    )
    return {
        "ok": True,
        "nexus": "unified",
        "version": _wb._app_version(),
        "port": int(os.environ.get("NEXUS_PORT", "8080")),
        "guard": guard_stats,
        "components": {
            "workbench": getattr(_wb, "get_council_bridge", None) is not None,
            "builder": getattr(_wb, "Builder", None) is not None,
            "craft": True,
            "monitoring": MONITORING_OK,
            "council": COUNCIL_OK,
            "council_members": len(COUNCIL_MEMBERS) if COUNCIL_OK else 0,
            "genome": COUNCIL_OK,
            "engine": ENGINE_OK,
            "engine_error": ENGINE_ERR or None,
            "topics": _topic_count(),
            "agents": {"framework": framework, "novamind": novamind,
                       "total": framework + novamind},
        },
        "council_error": COUNCIL_ERR or None,
    }


# ═══════════════════════════════════════════════════════════════════════
# /api/diag — تشخيص مفصّل: مصدر الملف، حالة المحرك، قائمة المسارات
# ═══════════════════════════════════════════════════════════════════════
@app.get("/api/diag")
def api_diag() -> Dict[str, Any]:
    """تشخيص فوري للبوابة: أي ملف مشغّل، هل المحرك حيّ، وكم مسار في كل طبقة."""

    def _paths(router: Any) -> List[str]:
        out: List[str] = []
        try:
            for r in getattr(router, "routes", []):
                p = getattr(r, "path", None) or getattr(r, "path_format", None)
                if p:
                    out.append(str(p))
        except Exception:
            pass
        return out

    _mod = globals().get("_engine")
    engine_app = getattr(_mod, "app", None) if _mod is not None else None
    parent_paths = _paths(app)
    engine_paths = _paths(engine_app) if engine_app is not None else []
    return {
        "ok": True,
        "loaded_from": str(Path(__file__).resolve()),
        "version": _wb._app_version(),
        "port": int(os.environ.get("NEXUS_PORT", "8080")),
        "engine_ok": bool(ENGINE_OK),
        "engine_err": ENGINE_ERR or None,
        "council_ok": bool(COUNCIL_OK),
        "council_err": COUNCIL_ERR or None,
        "mounts": {
            "engine": "/ (catch-all — unified_agent)",
            "workbench": "main.py parent app",
        },
        "routes_winning": "parent + gateway routes beat engine catch-all",
        "parent_routes_count": len(parent_paths),
        "engine_routes_count": len(engine_paths),
        "parent_routes": sorted(parent_paths),
        "engine_routes": sorted(engine_paths),
        "sys_path_head": sys.path[:6],
    }


# ═══════════════════════════════════════════════════════════════════════
# /api/monitoring/* — قراءة مراقبة الاستدعاءات (توكن/زمن/تكلفة). للقراءة فقط.
# ملاحظة: المُحرّك يملك ``/api/metrics`` (عدّادات observability مختلفة تماماً)،
# فالمسار هنا ``/api/monitoring/*`` لتفادي أيّ التباس في البادئة.
# ═══════════════════════════════════════════════════════════════════════
def _metrics_unavailable() -> Dict[str, Any]:
    """شكل الفشل الموحّد: ``ok=false`` + سبب صريح، بلا انهيار."""
    return {"ok": False, "error": MONITORING_ERR or "monitoring disabled",
            "stats": None}


@app.get("/api/monitoring/today")
def api_metrics_today() -> Dict[str, Any]:
    """إحصاء استدعاءات LLM المُسجَّلة اليوم (يُقرأ من ملفّ المراقبة)."""
    if _nexus_get_monitor is None:
        return _metrics_unavailable()
    try:
        stats = _nexus_get_monitor().get_today_stats()
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "stats": None}
    return {"ok": True, "scope": "today", "stats": stats}


@app.get("/api/monitoring/session")
def api_metrics_session() -> Dict[str, Any]:
    """إحصاء استدعاءات هذه الجلسة (في الذاكرة، بلا ملفّ)."""
    if _nexus_get_monitor is None:
        return _metrics_unavailable()
    try:
        stats = _nexus_get_monitor().get_session_stats()
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "stats": None}
    return {"ok": True, "scope": "session", "stats": stats}


@app.post("/api/monitoring/clear")
def api_metrics_clear() -> Dict[str, Any]:
    """يحذف سجلّ اليوم ويعيد عدد الاستدعاءات المحذوفة."""
    if _nexus_get_monitor is None:
        return {"ok": False, "error": MONITORING_ERR or "monitoring disabled",
                "cleared": 0}
    try:
        cleared = int(_nexus_get_monitor().clear_today())
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "cleared": 0}
    return {"ok": True, "cleared": cleared}


# ═══════════════════════════════════════════════════════════════════════
# /api/agents — الوكلاء المدمجون (حقيقي، من السجلّ لا رقم مكتوب يدويًا)
# ═══════════════════════════════════════════════════════════════════════
@app.get("/api/agents")
def api_agents() -> Dict[str, Any]:
    classes = _agent_classes()
    return {
        "total": len(classes),
        "agents": [
            {"id": getattr(c, "name", "?"), "group": getattr(c, "group", ""),
             "description": getattr(c, "description", "")}
            for c in classes
        ],
    }


# ═══════════════════════════════════════════════════════════════════════
# P4.5 — قناة نتائج المهام: كل تشغيل حقيقي يغذّي جينوم الوكيل
#   (المجلس يغذّي قناة الحُكم؛ هذه قناة ثانية مستقلة على نفس الصفّ)
# ═══════════════════════════════════════════════════════════════════════
def _record_task_outcome(agent_id: str, ok: bool, duration: float,
                         task: str = "",
                         rating: Optional[str] = None) -> None:
    """Fold one real run into the genome's task channel (fail-safe).

    Observability only: a missing or broken genome must never fail a request,
    so every error is swallowed here.  ``rating`` (المرحلة 1) يُدقّق نجاح
    المهمّة بجودة التقييم الذاتي — excellent=1.0 / good=0.75 / poor=0.4،
    وبلا تقييم يبقى السلوك القديم كما هو (نجاح صافٍ = 1.0).
    """
    try:
        from src.novamind.genome_v2 import get_genome_v2

        quality: Optional[float] = None
        if rating:
            try:
                from src.learning.reflection import rating_score

                quality = rating_score(rating)
            except Exception:
                quality = None
        get_genome_v2().observe_outcome(agent_id, ok, duration=duration,
                                       task=task[:200], quality=quality)
    except Exception:  # pragma: no cover - defensive
        pass


# ═══════════════════════════════════════════════════════════════════════
# P4.5 — جينوم الوكلاء: استرجاع المحفوظ + بذر العشرين + حفظ تلقائي
#   منطق القرص كلّه في src/novamind/genome_store.py، والجينوم يبقى نقياً.
# ═══════════════════════════════════════════════════════════════════════
GENOME_OK = False
GENOME_ERR: Optional[str] = None


def _install_genome_layer() -> None:
    """يُحمِّل جينوم الوكلاء من القرص، يبذر الوكّال العشرين، ويفعّل الحفظ.

    يُنادى من :func:`main` فقط (لا عند الاستيراد) حتى لا تكتب حزمة الاختبارات
    ملفّاً حقيقياً.  راصد فاشل آمن: أي خلل يُطبع ولا يمنع الإقلاع — الجينوم
    طبقة تعلّم، لا عصب الخدمة.
    """
    global GENOME_OK, GENOME_ERR
    try:
        from src.agents.manifest import all_manifests
        from src.novamind.genome_store import install

        genome = install(agent_ids=sorted(all_manifests()))
        GENOME_OK = True
        GENOME_ERR = None
        stats = genome.stats()
        print(f"   Genome    : ✅ {stats['agents']} وكيل · "
              f"{stats['observations']} حُكم · {stats['task_observations']} مهمّة")
    except Exception as exc:  # pragma: no cover - defensive
        GENOME_OK = False
        GENOME_ERR = str(exc)
        print(f"   Genome    : ❌ {exc}")


# ═══════════════════════════════════════════════════════════════════════
# المرحلة 1 — الذاكرة طويلة المدى + التقييم الذاتي
# كل دالة هنا راصد فاشل آمن: خللها يُبتلع ولا يكسر البثّ أبداً.
# ═══════════════════════════════════════════════════════════════════════
_INTERACTION_STORE: Any = None  # المخزن المُخبّأ، أو False بعد أول فشل


def _interaction_store() -> Any:
    """مخزن التفاعلات — ``None`` لو تعذّر (لا إعادة محاولة بعد الفشل)."""
    global _INTERACTION_STORE
    if _INTERACTION_STORE is None:
        try:
            from src.learning.interactions import get_interaction_store

            _INTERACTION_STORE = get_interaction_store()
        except Exception:
            _INTERACTION_STORE = False
    return _INTERACTION_STORE if _INTERACTION_STORE is not False else None


def _memory_block(task: str) -> str:
    """تفاعلات سابقة مشابهة (أي وكيل) تُحقن في نصّ النظام.

    التذكّر بين الوكّال مشترك عن قصد: درسٌ تعلّمه coder ينفع analyst، والترجيح
    يقتصرّ على تشابه السؤال.  ``""`` لو لا مخزن أو لا شيء/لا خلل.
    """
    try:
        store = _interaction_store()
        if store is None or not (task or "").strip():
            return ""
        from src.learning.reflection import memory_block

        return memory_block(store.similar(task))
    except Exception:  # pragma: no cover - defensive
        return ""


def _self_reflect(question: str, answer: str
                  ) -> tuple[Optional[str], Optional[str]]:
    """تقييم ذاتي للإجابة: ``(rating, reason)`` أو ``(None, None)`` عند أي خلل."""
    try:
        from src.learning.reflection import (
            REFLECTION_SYSTEM,
            build_reflection_prompt,
            parse_reflection,
        )

        res = get_router().generate(
            build_reflection_prompt(question, answer),
            system=REFLECTION_SYSTEM, role="fast")
        if not res.get("ok"):
            return None, None
        return parse_reflection(res.get("text") or "")
    except Exception:  # pragma: no cover - defensive
        return None, None


def _reflect_answer(question: str, text: str, system: str) -> tuple[
        str, str, Optional[str], Optional[str], bool, Optional[str]]:
    """تقييم ذاتي + إعادة محاولة واحدة للإجابة «الراكية».

    يعيد ``(text, answer, rating, reason, retried, retry_rating)``؛ أي خلل
    يعيد النصّ الأصلي بلا تقييم — البثّ لا ينكسر أبداً.
    """
    try:
        from src.learning.reflection import build_retry_system, should_retry

        rating, reason = _self_reflect(question, text)
        if not should_retry(rating):
            return text, text, rating, reason, False, None
        res2 = get_router().generate(
            question, system=build_retry_system(system, reason), role="fast")
        text2 = (res2.get("text") or "").strip()
        if not (res2.get("ok") and text2):
            return text, text, rating, reason, False, None
        retry_rating, _ = _self_reflect(question, text2)
        return text2, text2, rating, reason, True, retry_rating
    except Exception:  # pragma: no cover - defensive
        return text, text, None, None, False, None


def _save_interaction(agent_id: str, question: str, answer: str,
                      signal_ok: bool, rating: Optional[str],
                      reason: Optional[str], retried: bool,
                      retry_rating: Optional[str]) -> None:
    """يحفظ التفاعل في الذاكرة طويلة المدى (رصيدٌ فقط، لا يكسر الطلب)."""
    try:
        store = _interaction_store()
        if store is None:
            return
        from src.learning.reflection import awareness_gap

        gap = awareness_gap(rating, signal_ok,
                            retry_rating if retried else None)
        store.save(
            agent_id=agent_id, question=question, answer=answer,
            signal_ok=signal_ok, self_rating=rating,
            reflection_reason=reason, retry_used=retried,
            retried_rating=retry_rating if retried else None,
            awareness_gap=gap,
            lesson=reason if rating == "poor" else None,
        )
    except Exception:  # pragma: no cover - defensive
        pass


# ═══════════════════════════════════════════════════════════════════════
# /api/chat — دردشة موحّدة: LLM حقيقي عبر LLMRouter، بثّ SSE
# (plan → chunk → [DONE]) ليتوافق مع عميل CLI الحالي
# ═══════════════════════════════════════════════════════════════════════
@app.post("/api/chat")
def api_chat(req: ChatRequest) -> Any:
    message = (req.message or "").strip()[:4000]
    system = _agent_system(req.agent, message)
    agent_id = req.agent or "default"

    def gen() -> Iterator[str]:
        """SSE: plan → chunk → [DONE].

        المرحلة 1: تقييم ذاتي بعد كل إجابة، وإعادة محاولة واحدة عند «ركيك»،
        وحفظ التفاعل كاملًا في الذاكرة طويلة المدى — كلها في الخيط نفسه
        قبل البثّ (المخرجات مُخزّنة أصلاً) فلا يتغيّر ترتيب الأحداث، وكل
        طبقة راصد فاشلة تبتلع نفسها في ``finally`` مع قناة الجينوم.
        """
        started = time.monotonic()
        ok = False
        ran = False
        rating: Optional[str] = None
        reason: Optional[str] = None
        retried = False
        retry_rating: Optional[str] = None
        answer = ""
        try:
            yield _sse({"type": "plan", "agent": req.agent or "default",
                        "conversation_id": req.conversation_id})
            if not message:
                yield _sse({"type": "chunk", "content": "(رسالة فارغة)"})
                return
            ran = True
            try:
                res = get_router().generate(message, system=system,
                                            role="fast")
                text = (res.get("text") or "").strip()
                if res.get("ok") and text:
                    ok = True
                    (text, answer, rating, reason,
                     retried, retry_rating) = _reflect_answer(
                        message, text, system)
                    yield _sse({"type": "chunk", "content": text,
                                "provider": res.get("provider", ""),
                                "reflection": {"rating": rating,
                                               "reason": reason},
                                "retried": retried})
                else:
                    yield _sse({"type": "error",
                                "content": res.get("error")
                                or "لا يوجد مزود متاح"})
            except Exception as e:  # pragma: no cover - defensive
                yield _sse({"type": "error",
                            "content": f"{type(e).__name__}: {e}"})
            yield _sse("[DONE]")
        finally:
            if ran:
                _save_interaction(agent_id, message, answer, ok, rating,
                                  reason, retried, retry_rating)
                _record_task_outcome(agent_id, ok, time.monotonic() - started,
                                     task=message, rating=rating)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# ═══════════════════════════════════════════════════════════════════════
# /api/council/* — المجلس الحيّ (6 أعضاء) + الجلسات
# ═══════════════════════════════════════════════════════════════════════
@app.post("/api/council/debate")
async def api_council_debate(req: CouncilRequest) -> Dict[str, Any]:
    if not COUNCIL_OK:
        return {"ok": False, "error": "Council غير متوفر: " + COUNCIL_ERR}
    topic = (req.topic or "").strip()[:1000]
    if not topic:
        return {"ok": False, "error": "topic مطلوب"}
    rounds = _clamp_rounds(req.rounds)
    try:
        result = await asyncio.to_thread(
            lambda: get_council().debate(topic, rounds=rounds))
        return {"ok": True, "rounds": rounds, "result": result}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


@app.post("/api/council/stream")
def api_council_stream(req: CouncilRequest) -> Any:
    """بثّ المداولة الحيّة SSE — مخرَج المجلس نفسه هو الـ payload."""
    if not COUNCIL_OK:
        return JSONResponse(
            {"ok": False, "error": "Council غير متوفر: " + COUNCIL_ERR},
            status_code=503)
    topic = (req.topic or "").strip()[:1000] or "موضوع غير محدّد"
    rounds = _clamp_rounds(req.rounds)

    def gen() -> Iterator[str]:
        try:
            for ev in get_council().debate_stream(topic, rounds=rounds):
                yield _sse(ev)
        except Exception as e:  # pragma: no cover - defensive
            yield _sse({"type": "error", "message": f"{type(e).__name__}: {e}"})
        yield _sse("[DONE]")

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.get("/api/council/sessions")
def api_council_sessions(limit: int = 50) -> Dict[str, Any]:
    if not COUNCIL_OK:
        return {"sessions": [], "error": COUNCIL_ERR}
    lim = max(1, min(int(limit or 50), 200))
    try:
        return {"sessions": get_store_singleton().list_council_sessions(limit=lim)}
    except Exception as e:
        return {"sessions": [], "error": f"{type(e).__name__}: {e}"}


@app.get("/api/council/sessions/{sid}")
def api_council_session_get(sid: str) -> Any:
    if not COUNCIL_OK:
        raise HTTPException(status_code=503, detail="Council غير متوفر")
    session = get_store_singleton().get_council_session(sid)
    if session is None:
        raise HTTPException(status_code=404, detail="council session not found")
    return session


@app.delete("/api/council/sessions/{sid}")
def api_council_session_delete(sid: str) -> Dict[str, Any]:
    if not COUNCIL_OK:
        raise HTTPException(status_code=503, detail="Council غير متوفر")
    if not get_store_singleton().delete_council_session(sid):
        raise HTTPException(status_code=404, detail="council session not found")
    return {"deleted": True, "id": sid}


# ═══════════════════════════════════════════════════════════════════════
# /api/genome* — جينوم الوكلاء (الترتيب، التفاصيل، التصدير/الاستيراد، إعادة تدريب)
# ملاحظة: export/import تُسجَّل قبل {agent_id} حتى لا يُلتقطا كمعرّف.
# ═══════════════════════════════════════════════════════════════════════
@app.get("/api/genome")
def api_genome_list() -> Dict[str, Any]:
    if not COUNCIL_OK:
        return {"agents": [], "error": COUNCIL_ERR}
    try:
        return {"agents": get_genome().rank()}
    except Exception as e:
        return {"agents": [], "error": f"{type(e).__name__}: {e}"}


@app.get("/api/genome/export")
def api_genome_export() -> Any:
    if not COUNCIL_OK:
        raise HTTPException(status_code=503, detail="Genome غير متوفر")
    payload = get_genome().export()
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": 'attachment; filename="genome.json"'})


@app.post("/api/genome/import")
def api_genome_import(body: Dict[str, Any]) -> Dict[str, Any]:
    if not COUNCIL_OK:
        raise HTTPException(status_code=503, detail="Genome غير متوفر")
    return {"imported": get_genome().import_(body or {})}


@app.get("/api/genome/{agent_id}")
def api_genome_detail(agent_id: str) -> Any:
    if not COUNCIL_OK:
        raise HTTPException(status_code=503, detail="Genome غير متوفر")
    agent = get_genome().detail(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    return agent


@app.patch("/api/genome/{agent_id}")
def api_genome_patch(agent_id: str, req: GenomePatch) -> Any:
    if not COUNCIL_OK:
        raise HTTPException(status_code=503, detail="Genome غير متوفر")
    ok = get_store_singleton().update_agent(agent_id, name=req.name,
                                            persona=req.persona)
    if not ok:
        raise HTTPException(status_code=404, detail="agent not found")
    return get_store_singleton().get_agent(agent_id)


@app.post("/api/genome/{agent_id}/reset")
def api_genome_reset(agent_id: str) -> Any:
    if not COUNCIL_OK:
        raise HTTPException(status_code=503, detail="Genome غير متوفر")
    agent = get_genome().reset(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    return agent


# ═══════════════════════════════════════════════════════════════════════
# /api/mcp/tools — طقم أدوات MCP لسطح الإطار (30 أداة) — للعرض في الواجهة
# ═══════════════════════════════════════════════════════════════════════
_MCP_SERVER: Any = None


def _framework_mcp_server() -> Any:
    """يُبنى مرّة واحدة (lazy) ويعاد استخدامه — بناء الوكلاء ليس مجانياً."""
    global _MCP_SERVER
    if _MCP_SERVER is None:
        from src.mcp.framework import build_framework_server
        _MCP_SERVER = build_framework_server(root=BASE_DIR)
    return _MCP_SERVER


def _mcp_group(name: str) -> str:
    if name.startswith("agent_"):
        return "agents"
    if name.startswith("git_"):
        return "git"
    if name.startswith("security_"):
        return "security"
    return "workspace"


@app.get("/api/mcp/tools")
def api_mcp_tools() -> Dict[str, Any]:
    """أدوات خادم MCP لسطح الإطار: الاسم، الوصف، والمجموعة، ومخطّط الإدخال."""
    try:
        specs = _framework_mcp_server().list_tools()["tools"]
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "total": 0, "tools": []}
    tools = [
        {
            "name": t.get("name", ""),
            "description": t.get("description", ""),
            "group": _mcp_group(t.get("name", "")),
            "input_schema": t.get("inputSchema", {}),
        }
        for t in specs
    ]
    return {"ok": True, "total": len(tools), "tools": tools}


# لوحة المحرّك الموحّدة (web/unified_ui.html): الوالد يفوز بـ "/" لذا يحتاج
# المحرك مساراً صريحاً — /ui = نفس الصفحة التي يخدمها unified_agent وحده
# (المجلس الحيّ + الجينوم + الأكاديمية) على منفذ الخدمة نفسه.
@app.get("/ui", response_class=HTMLResponse)
async def engine_ui() -> HTMLResponse:
    ui_path = BASE_DIR / "web" / "unified_ui.html"
    if ui_path.exists():
        return HTMLResponse(ui_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>web/unified_ui.html not found</h1>", status_code=404)


# ═══════════════════════════════════════════════════════════════════════
# 3) Engine — mount أخيراً وبقصد: مسارات الوورك‌بنش ومساراتي أعلاه تُسجَّل
#    قبله فتفوز، والمحرّك يلتقط كل ما تبقّى (conversations / traces /
#    pipeline / workspace / offline). الترتيب = العقد نفسه.
# ═══════════════════════════════════════════════════════════════════════
# ✅ v3.2.0: exec sandbox — يجب أن يكون قبل app.mount('/')
try:
    from exec_sandbox import router as exec_router
    app.include_router(exec_router)
    print('✅ exec_sandbox مركّب')
except Exception as _exec_e:
    print(f'⚠️ exec_sandbox لم يُركّب: {_exec_e}')

if ENGINE_OK:
    app.mount("/", _engine.app)


# ═══════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════
def acquire_instance_lock(port: int) -> Optional[Any]:
    """حاجز النسخة الواحدة لهذا المنفذ — توقّف أي محاولة تشغيل ثانية.

    تُعيد الفتحة المقفلة (أبقها مربوطة باسم في ``main`` — يُفلت ``flock``
    تلقائياً عند موت العملية)، أو ``None`` إذا كانت نسخة أخرى من البوابة
    تخدم هذا المنفذ بالفعل. هذا ما يوقف التكرار بين runit (``sv restart``)
    و ``nexus start`` (``nohup``): النسخة الثانية ترفض الإقلاع بدل أن
    تُنتج نسخة يتيمة على نفس المنفذ.
    """
    lock_dir = Path(os.environ.get("NEXUS_LOCK_DIR") or str(BASE_DIR / "logs"))
    try:
        lock_dir.mkdir(parents=True, exist_ok=True)
        handle = (lock_dir / f"nexus-agent-{port}.lock").open("a+")
    except OSError as exc:  # pragma: no cover - defensive
        # لا مكان للقفل ⇒ نكمل بلا حاجز (سيحكم ربط المنفذ إن حاول نسختان)
        print(f"⚠️ تعذّر فتح ملف القفل ({exc}) — بلا حاجز نسخة واحدة")
        return open(os.devnull, "a+")  # type: ignore[return-value]
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()  # نسخة أخرى تحمل القفل — لا نُبقيه مفتوحاً
        return None
    handle.seek(0)
    handle.truncate()
    handle.write(f"{os.getpid()}\n")
    handle.flush()
    return handle


# WIP v3.2.0 (جلسة أخرى): /simple.html — يبقى كما هو حتى يُسلَّم صاحبه
@app.get("/simple.html")
def serve_simple():
    return FileResponse("web/simple.html")

def main() -> None:
    port = int(os.environ.get("NEXUS_PORT", "8080"))
    _lock = acquire_instance_lock(port)  # noqa: F841 — يبقى حيّاً هنا = القفل محفوظ
    if _lock is None:
        print(f"⛔ نسخة أخرى من البوابة تعمل بالفعل على :{port} — توقّف.")
        print("   أوقفها أولاً:  sv stop nexus-core   أو   nexus stop")
        raise SystemExit(1)
    import uvicorn
    print(f"🚀 Nexus-Core Unified v{_wb._app_version()} على :{port}")
    print(f"   Workbench : ✅ {len(app.routes)} route")
    print("   Engine    : " + (
        "✅ unified_agent" if ENGINE_OK else f"❌ {ENGINE_ERR}"))
    print("   Council   : " + (
        f"✅ {len(COUNCIL_MEMBERS)} أعضاء" if COUNCIL_OK else f"❌ {COUNCIL_ERR}"))
    _install_genome_layer()
    print(f"   Agents    : {len(_agent_classes())}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
