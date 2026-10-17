"""سطح HTTP لقاعدة المعرفة المشتركة (``/api/knowledge/*``).

يُركَّب على البوابة الموحّدة، ومفصول في وحدته حتى يبقى ``base``/``inject``
قابلين للاستيراد بلا FastAPI مثبّتاً.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

from .base import KnowledgeBase, get_knowledge_base

__all__ = ["build_router", "register"]


def register(app: Any, kb: Optional[KnowledgeBase] = None) -> APIRouter:
    """يسجّل راوتات المعرفة على ``app``.

    ``app.include_router`` **مؤجَّل** في إصدارات FastAPI الحديثة: يحفظ الراوتات
    في عنصر نائب ``_IncludedRouter`` ويوسّعها لاحقاً، وتطبيق فرعي يُركَّب بـ
    ``mount`` لا يمرّ بذلك التوسيع أبداً → ``/api/knowledge/*`` يعطي 404 داخل
    البوابة رغم نجاحه على تطبيق مجرّد. إضافة الراوتات الحقيقية مباشرة تُلغي
    العنصر النائب.
    """
    router = build_router(kb)
    app.router.routes.extend(router.routes)
    return router


def build_router(kb: Optional[KnowledgeBase] = None) -> APIRouter:
    """يبني راوتر المعرفة (``kb`` قابل للحقن في الاختبارات)."""
    router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])
    base = kb or get_knowledge_base()

    @router.get("")
    async def knowledge_list() -> Dict[str, Any]:
        """كل الوثائق (بلا محتوى) + إحصاء القاعدة."""
        docs = base.all_docs()
        return {
            "count": len(docs),
            "stats": base.stats(),
            "docs": [doc.to_dict() for doc in docs],
        }

    @router.get("/{name}")
    async def knowledge_doc(name: str) -> Dict[str, Any]:
        """وثيقة واحدة بمحتواها الكامل، أو 404."""
        doc = base.load(name)
        if doc is None:
            raise HTTPException(status_code=404, detail="knowledge doc not found")
        return {**doc.to_dict(), "content": doc.content}

    return router
