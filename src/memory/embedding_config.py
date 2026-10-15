"""Embedding provider configuration — one env var picks the RAG embedder.

``NEXUS_EMBEDDINGS`` selects the embedder used by the Council's RAG memory:

* ``hashing`` (default) — the dependency-free :class:`HashingEmbedder`
  (offline, deterministic, 512-d). Keeps the historical ``rag.db`` file.
* ``gemini`` — Google Gemini ``text-embedding-004`` (768-d, semantic).
* ``openai`` — OpenAI ``text-embedding-3-small`` (1536-d, semantic).

Non-default providers need the ``openai`` package *and* an API key; if either
is missing the resolver **falls back to hashing** (with a reason string)
instead of breaking the Council at boot.

Because a ``sqlite-vec`` table is created with a fixed vector length, every
non-default provider gets its OWN database file
(``rag-<provider>-<dim>.db``). The default provider keeps ``rag.db`` so existing
memory is never lost when the flag is left alone.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

__all__ = [
    "ENV_VAR",
    "DEFAULT_PROVIDER",
    "DEFAULT_DIM",
    "EMBEDDER_DIMS",
    "ResolvedEmbedder",
    "resolve_spec",
    "dim_for",
    "store_filename",
    "default_store_dir",
    "store_path_for",
    "build_embedder",
    "resolve_rag",
]

ENV_VAR = "NEXUS_EMBEDDINGS"
DEFAULT_PROVIDER = "hashing"
DEFAULT_DIM = 512

# أيقونة → الاسم القانوني (تُطبَّع الحروف صغيرة قبل البحث)
_ALIASES = {
    "hashing": "hashing",
    "hash": "hashing",
    "default": "hashing",
    "builtin": "hashing",
    "gemini": "gemini",
    "google": "gemini",
    "openai": "openai",
}

# بُعد كل مزود (يطابق مخرجات النموذج الفعلية)
EMBEDDER_DIMS = {"hashing": 512, "gemini": 768, "openai": 1536}


def resolve_spec(name: Optional[str] = None, env: Optional[dict] = None) -> str:
    """يحوّل اسم المزود/متغير البيئة إلى الاسم القانوني.

    الأسبقية: ``name`` (وسيطة) → ``env[NEXUS_EMBEDDINGS]`` → الافتراضي.
    القيمة الفارغة أو ``auto`` تعني الافتراضي. اسم غير معروف يرفع ValueError.
    """
    env = os.environ if env is None else env  # type: ignore[assignment]
    raw = name if name is not None else env.get(ENV_VAR, "")  # type: ignore[union-attr]
    spec = (raw or "").strip().lower()
    if spec in ("", "auto"):
        spec = DEFAULT_PROVIDER
    if spec not in _ALIASES:
        raise ValueError(
            f"مزود embeddings غير معروف: {raw!r} "
            f"(المتاح: {', '.join(sorted(set(_ALIASES.values())))})"
        )
    return _ALIASES[spec]


def dim_for(spec: str) -> int:
    """بُعد المتجه لمزود قانوني (512 افتراضياً)."""
    return EMBEDDER_DIMS.get(spec, DEFAULT_DIM)


def default_store_dir() -> str:
    """مجلد بيانات nexus الافتراضي (``~/.nexus/data``)."""
    return os.path.join(os.path.expanduser("~"), ".nexus", "data")


def store_filename(spec: str, dim: Optional[int] = None) -> str:
    """اسم ملف قاعدة المتجهات — الافتراضي يحتفظ بـ ``rag.db`` القديم."""
    if spec == DEFAULT_PROVIDER:
        return "rag.db"
    return f"rag-{spec}-{dim if dim is not None else dim_for(spec)}.db"


def store_path_for(spec: str, base_dir: Optional[str] = None,
                   dim: Optional[int] = None) -> str:
    """المسار الكامل لقاعدة المتجهات لمزود معيّن."""
    base = base_dir or default_store_dir()
    return os.path.join(base, store_filename(spec, dim))


def build_embedder(spec: str, **kwargs: Any) -> Any:
    """يبني الـ embedder للمزود.

    يُرجع ``(embedder, dim, fallback_reason)``. عند فشل مزوّد غير افتراضي
    (مكتبة ناقصة / مفتاح غائب) يرجع إلى hashing ويكون ``fallback_reason``
    نصاً يشرح السبب؛ وإلا يكون ``None``.
    """
    from src.memory.embeddings import HashingEmbedder

    spec = resolve_spec(spec)
    if spec == DEFAULT_PROVIDER:
        return HashingEmbedder(dim=DEFAULT_DIM, **kwargs), DEFAULT_DIM, None

    try:
        from src.memory.providers.base import get_provider
        provider = get_provider(spec)
        return provider, dim_for(spec), None
    except Exception as exc:  # ImportError / ValueError / missing key
        reason = f"{spec} غير متاح ({type(exc).__name__}: {exc}) — رجعنا إلى hashing"
        return HashingEmbedder(dim=DEFAULT_DIM), DEFAULT_DIM, reason


@dataclass
class ResolvedEmbedder:
    """نتيجة حلّ إعدادات التضمين (embedder + بُعده + مسار التخزين)."""

    spec: str
    embedder: Any
    dim: int
    path: str
    fallback_reason: Optional[str] = None


def resolve_rag(name: Optional[str] = None, env: Optional[dict] = None,
                base_dir: Optional[str] = None) -> ResolvedEmbedder:
    """يحلّ كل إعدادات RAG من متغير البيئة بخطوة واحدة.

    لا يرفع استثناءً أبداً: أي اسم غير معروف يرجع إلى hashing مع سبب.
    """
    fallback = None
    try:
        spec = resolve_spec(name, env)
    except ValueError as exc:
        fallback = str(exc)
        spec = DEFAULT_PROVIDER

    embedder, dim, reason = build_embedder(spec)
    if reason:
        # المزوّد رجع فعلياً إلى hashing → اعتبره الافتراضي حتى يبقى rag.db ومتجهه 512
        fallback = fallback or reason
        spec = DEFAULT_PROVIDER
        dim = DEFAULT_DIM
    path = store_path_for(spec, base_dir=base_dir, dim=dim)
    return ResolvedEmbedder(spec=spec, embedder=embedder, dim=dim,
                            path=path, fallback_reason=fallback)
