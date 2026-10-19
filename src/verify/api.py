"""سطح HTTP للتحقق بالتنفيذ (``/api/verify/*``).

يُركَّب في البوابة الموحّدة عبر ``unified_agent.py``. منفصل عن المحرّك النقي كي
يظلّ ``engine`` قابلاً للاستيراد (والاختبار) بلا FastAPI.

``register`` يستعمل ``app.router.routes.extend`` لا ``include_router`` — الأخير
مؤجَّل في FastAPI الحديثة ويسقط عند المرور بـ``mount`` (نفس درس التدريب/المهارات).

كل المسارات **قراءة/تنفيذ فقط** بلا كتابة على القرص.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .engine import MAX_ATTEMPTS, fix_loop, verify_by_execution
from .generators import llm_generate

__all__ = ["FixRequest", "VerifyRequest", "build_router", "register"]


class VerifyRequest(BaseModel):
    """جسم ``POST /api/verify/run``."""

    code: str = Field(..., min_length=1)
    language: str = Field(default="python", max_length=32)
    tests: str = Field(default="")
    stdin: str = Field(default="")
    timeout: int = Field(default=10, ge=1, le=20)


class FixRequest(VerifyRequest):
    """جسم ``POST /api/verify/fix`` — يعيد المحاولة عبر الـLLM عند الفشل."""

    task: str = Field(default="", max_length=2000)
    max_attempts: int = Field(default=3, ge=1, le=MAX_ATTEMPTS)


def _languages() -> List[str]:
    """لغات الصندوق المتاحة فعلاً (``[]`` إن كان الصندوق غائباً)."""
    try:
        from exec_sandbox import LANGS
    except Exception:
        return []
    return sorted(LANGS)


def build_router() -> APIRouter:
    """يبني راوتر التحقق (بلا حالة — لا شيء يُحقَن)."""
    router = APIRouter(prefix="/api/verify", tags=["verify"])

    @router.get("/tools")
    async def verify_tools() -> Dict[str, Any]:
        """ما الذي يستطيع هذا السطح فعله الآن — بصدق."""
        langs = _languages()
        return {
            "ok": True,
            "available": bool(langs),
            "languages": langs,
            "max_attempts": MAX_ATTEMPTS,
            "generator": "llm",
        }

    @router.post("/run")
    async def verify_run(req: VerifyRequest) -> Dict[str, Any]:
        """ينفّذ الكود ويُعيد الحكم (بلا إصلاح)."""
        result = verify_by_execution(
            req.code,
            language=req.language,
            tests=req.tests,
            stdin=req.stdin,
            timeout=req.timeout,
        )
        return result.to_dict()

    @router.post("/fix")
    async def verify_fix(req: FixRequest) -> Dict[str, Any]:
        """ينفّذ، وعند الفشل يطلب من الـLLM إصلاحاً ويعيد المحاولة."""
        result = fix_loop(
            req.task,
            req.code,
            language=req.language,
            tests=req.tests,
            stdin=req.stdin,
            timeout=req.timeout,
            max_attempts=req.max_attempts,
            generate=llm_generate,
        )
        return result.to_dict()

    return router


def register(app: Any) -> APIRouter:
    """يركّب مسارات التحقق على ``app`` مباشرةً (لا ``include_router`` مؤجَّل)."""
    router = build_router()
    app.router.routes.extend(router.routes)
    return router


def router_for_app(app: Any) -> APIRouter:  # pragma: no cover - توافق مع نمط التدريب
    """توافق: يبني راوتراً (لا حالة عمليّة لديه)."""
    return build_router()
