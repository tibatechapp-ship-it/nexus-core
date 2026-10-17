"""سطح HTTP لنظام المهارات (``/api/skills/*``).

يُركَّب على البوابة الموحّدة، ومفصول في وحدته حتى يبقى ``loader``/``inject``
قابلين للاستيراد بلا FastAPI مثبّتاً.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

from .inject import get_skill_loader
from .loader import SkillLoader

__all__ = ["build_router", "register"]


def register(app: Any, loader: Optional[SkillLoader] = None) -> APIRouter:
    """يسجّل راوتات المهارات على ``app``.

    ``app.include_router`` **مؤجَّل** في إصدارات FastAPI الحديثة: يحفظ الراوتات
    في عنصر نائب ``_IncludedRouter`` ويوسّعها لاحقاً، وتطبيق فرعي يُركَّب بـ
    ``mount`` لا يمرّ بذلك التوسيع أبداً → ``/api/skills/*`` يعطي 404 داخل
    البوابة رغم نجاحه على تطبيق مجرّد. إضافة الراوتات الحقيقية مباشرة تُلغي
    العنصر النائب.
    """
    router = build_router(loader)
    app.router.routes.extend(router.routes)
    return router


def build_router(loader: Optional[SkillLoader] = None) -> APIRouter:
    """يبني راوتر المهارات (``loader`` قابل للحقن في الاختبارات)."""
    router = APIRouter(prefix="/api/skills", tags=["skills"])
    base = loader or get_skill_loader()

    @router.get("")
    async def skills_list() -> Dict[str, Any]:
        """كل المهارات (اسم + وصف) + مصادرها."""
        skills = []
        for name in base.list_skills():
            skill = base.load(name)
            if skill is not None:
                skills.append({"name": skill.name, "description": skill.description})
        return {
            "count": len(skills),
            "skills": skills,
            "sources": base.sources(),
        }

    @router.get("/{name}")
    async def skill_detail(name: str) -> Dict[str, Any]:
        """مهارة واحدة بمحتواها الكامل، أو 404."""
        skill = base.load(name)
        if skill is None:
            raise HTTPException(status_code=404, detail="skill not found")
        return {
            "name": skill.name,
            "description": skill.description,
            "content": skill.content,
        }

    return router
