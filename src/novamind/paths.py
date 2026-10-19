"""مسارات قابلة للكتابة — سلسلة تراجع آمنة على Termux/Android.

الخلفية: عدّة وحدات داخل طبقة novamind كانت تفترض وجود ``/var/lib`` أو
``/var/log``. على Android/Termux الجذر ``/`` للقراءة فقط (EROFS) ولا يوجد
``/var`` أصلًا، فكان مجرّد
``Path("/var/log/novamind").mkdir(parents=True, exist_ok=True)``
يسقط بـ ``OSError: [Errno 30] Read-only file system: '/var'`` — وهذا وحده كان
يُفشل تحميل الوكلاء عبر ``novamind.agents.factory``.

هذه الوحدة تُعطي جذرًا واحدًا قابلًا للكتابة بترتيب أوّليات ثابت:

1. قيمة ``env_var`` إن كانت مضبوطة (افتراضيًا ``$NEXUS_DATA_DIR``،
   ويمكن تمرير ``NOVAMIND_HOME`` للمحرّك القديم).
2. المسارات المرغوبة ``preferred`` (افتراضيًا ``/var/lib/nexus`` ثم
   ``/var/tmp/nexus``) — تبقى كما هي على الخوادم حيث ``/var`` قابل للكتابة.
3. ``~/.cache/nexus``.
4. ``<tempdir>/nexus``.

أوّل مرشّح ننجح في إنشائه ويكون قابلًا للكتابة هو الذي يُعاد. الدوال هنا لا
تُسقط أيّ استثناء: لو فشل كل شيء نُرجع ``<tempdir>/nexus`` (مضمون عمليًا)
ونسجّل تحذيرًا واحدًا. التحذير ليس خطأً: هذه حالة متوقّعة على الهاتف.
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import List, Optional, Sequence

logger = logging.getLogger("novamind.paths")

#: متغيّر البيئة العام لجذر بيانات nexus (يتقدّم على كل المرشّحين).
DATA_DIR_ENV = "NEXUS_DATA_DIR"

#: المرشّحون الافتراضيون بعد ``env_var`` — ترتيب الخوادم المألوف أولًا.
DEFAULT_PREFERRED: tuple = ("/var/lib/nexus", "/var/tmp/nexus")

#: كل مرشّح مُعلَّم مرة واحدة فقط حتى لا يتكرّر التحذير في كل بناء كائن.
_warned: set = set()


def _warn_once(path: Path, reason: str) -> None:
    """سجّل سبب تخطّي مرشّح مرّة واحدة (بلا ضجيج في السجلّات)."""
    key = f"{path}\0{reason}"
    if key in _warned:
        return
    _warned.add(key)
    logger.warning("مسار غير قابل للكتابة: %s (%s) — ننتقل للمرشّح التالي", path, reason)


def candidates(
    env_var: str = DATA_DIR_ENV,
    preferred: Sequence[str] = DEFAULT_PREFERRED,
) -> List[Path]:
    """مرشّحو جذر البيانات القابل للكتابة بالترتيب."""
    paths: List[Path] = []
    override = os.environ.get(env_var) if env_var else None
    if override:
        paths.append(Path(override))
    paths.extend(Path(item) for item in preferred)
    paths.append(Path.home() / ".cache" / "nexus")
    paths.append(Path(tempfile.gettempdir()) / "nexus")
    return paths


def first_writable(paths: Sequence[Path]) -> Optional[Path]:
    """أوّل مسار يُنشأ بنجاح *ويكون* قابلًا للكتابة، وإلا ``None``.

    تُنشأ المجلّدات الأب عند الحاجة (``parents=True``) للمسارات المتداخلة مثل
    ``/var/lib/nexus``.
    """
    for path in paths:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # EROFS على Android، EACCES على خادم مقيّد…
            _warn_once(path, exc.strerror or type(exc).__name__)
            continue
        if os.access(path, os.W_OK):
            return path
        _warn_once(path, "غير قابل للكتابة")
    return None


def writable_root(
    env_var: str = DATA_DIR_ENV,
    preferred: Sequence[str] = DEFAULT_PREFERRED,
) -> Path:
    """جذر بيانات مضمون قابل للكتابة (لا يُسقط استثناءً أبدًا)."""
    resolved = first_writable(candidates(env_var, preferred))
    if resolved is not None:
        return resolved
    fallback = Path(tempfile.gettempdir()) / "nexus"
    fallback.mkdir(parents=True, exist_ok=True)
    logger.warning("لا مسار قابل للكتابة من المرشّحين — نستخدم %s", fallback)
    return fallback


def writable_path(
    relative: str,
    env_var: str = DATA_DIR_ENV,
    preferred: Sequence[str] = DEFAULT_PREFERRED,
) -> Path:
    """مسار ملف داخل جذر قابل للكتابة مع إنشاء المجلّد الأب."""
    path = writable_root(env_var=env_var, preferred=preferred) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


__all__ = [
    "DATA_DIR_ENV",
    "DEFAULT_PREFERRED",
    "candidates",
    "first_writable",
    "writable_path",
    "writable_root",
]
