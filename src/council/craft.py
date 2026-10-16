"""Craft — توليد كود فعلي مباشرة من وصف حرّ (v1.12).

علاقة هذا المكوّن بـ ``builder.py``:

* ``Builder`` يبني **من قرار مجلس** (حكم + ثقة + توصية) → خطة/ملفات.
* ``Craft`` يبني **من وصف حرّ مباشرة** بلا مداولة سابقة، ثم اختيارياً يطلب
  مراجعة الكود المولَّد من المجلس نفسه — مراجعة **منتَج** لا نيّة.

مبادئ التصميم:

* **بوابة مسارات موحّدة**: يُعاد استخدام ``_safe_rel_path`` من ``builder``
  (مصدر واحد للحقيقة الأمنية) + قائمة امتدادات مسموحة صريحة.
* **دليل إلزامي**: ``py_compile`` لكل ملف ``.py``. فشل الترجمة يظهر صراحةً في
  ``proof.ok=false`` — لا نخفي الخطأ ولا نعلن نجاحاً بلا تحقّق.
* **حدود صارمة**: أقل عدد ملفات ومجموع أحجام محدود (لا انفجار مخرجات).
"""
from __future__ import annotations

import json
import os
import py_compile
import re
import sys
import tempfile
import time
from typing import Any, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:  # مصدر واحد لبوابة المسارات + جذر البناء
    from src.council.builder import _safe_rel_path, builds_root
except Exception:  # pragma: no cover - احتياط فقط
    _safe_rel_path = None  # type: ignore[assignment]

    def builds_root() -> str:
        return os.path.join(os.path.expanduser("~"), ".nexus", "data", "builds")


__all__ = ["CraftError", "generate_code"]

BUILD_DIR = None  # يُحسب عند الطلب عبر builds_root() (يحترم NEXUS_BUILDS)
ALLOWED_EXT = (".py", ".md", ".txt", ".json", ".sh", ".html", ".css", ".js")
MAX_FILES = 10
MAX_BYTES = 50_000
MAX_TOKENS = 3500


class CraftError(Exception):
    """خطأ في توليد/كتابة الكود — يُعاد للمستخدم برسالة واضحة."""


def _router() -> Optional[Any]:
    """مزوّد LLM الموحّد (novamind). ``None`` إن تعذّر الاستيراد."""
    try:
        from novamind.core.llm_router import LLMRouter

        return LLMRouter()
    except Exception:
        return None


def _safe_path(base: str, rel: str) -> str:
    """يبني مساراً مطلقاً آمناً داخل ``base`` أو يرفع ``CraftError``."""
    norm = _safe_rel_path(rel)
    if not norm:
        raise CraftError("مسار غير آمن: " + str(rel)[:60])
    if not norm.endswith(ALLOWED_EXT):
        raise CraftError("امتداد غير مسموح: " + norm)
    return os.path.join(base, norm)


def _parse_files(text: str) -> list:
    """يحلّل مخرجات المولّد إلى قائمة ``(path, content)``.

    يقبل مصفوفة JSON مباشرة ``[{...}]`` أو كائناً يحوي مفتاح ``files``.
    """
    s = (text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```\s*$", "", s).strip()
    if not s:
        raise CraftError("مخرجات فارغة من المولّد")

    data: Any = None
    if s.lstrip().startswith("{"):
        i, j = s.find("{"), s.rfind("}")
        if i == -1 or j <= i:
            raise CraftError("لم أجد JSON في مخرجات المولّد")
        try:
            obj = json.loads(s[i:j + 1])
        except Exception as exc:
            raise CraftError("JSON غير صالح: " + str(exc)[:80])
        data = obj.get("files", []) if isinstance(obj, dict) else []
    else:
        i, j = s.find("["), s.rfind("]")
        if i == -1 or j <= i:
            raise CraftError("لم أجد مصفوفة JSON في مخرجات المولّد")
        try:
            data = json.loads(s[i:j + 1])
        except Exception as exc:
            raise CraftError("JSON غير صالح: " + str(exc)[:80])

    if not isinstance(data, list) or not data:
        raise CraftError("لا ملفات في مخرجات المولّد")
    files = []
    for item in data[:MAX_FILES]:
        if isinstance(item, dict) and item.get("path"):
            files.append((str(item["path"]).strip(), str(item.get("content", ""))))
    if not files:
        raise CraftError("لا ملفات صالحة (كل عنصر يحتاج path و content)")
    return files


_GEN_SYSTEM = (
    "أنت مولّد كود. أعد **مصفوفة JSON فقط** بلا أي نص أو شرح خارجها، بالشكل: "
    '[{"path": "main.py", "content": "الكود الكامل"}]. '
    "مسارات نسبية فقط بلا `..` وبلا مسار مطلق."
)


def _review(files: list, query: str) -> dict:
    """المجلس يراجع الكود المولَّد — يصوّت على صلاحيته للدمج."""
    try:
        from src.council.rag_bridge import get_council_bridge

        body = "\n\n".join("━━━ " + p + " ━━━\n" + c[:1500] for p, c in files)
        res = get_council_bridge().deliberate_with_memory(
            "راجع هذا الكود المولَّد للمطلوب: «" + query[:120] +
            "». هل يصلح للدمج؟\n\n" + body
        )
        return {
            "verdict": str(getattr(res, "verdict", "unknown")),
            "score": float(getattr(res, "score", 0) or 0),
            "rounds": int(getattr(res, "rounds", 0) or 0),
        }
    except Exception as exc:
        return {"verdict": "error", "error": str(exc)[:100]}


def generate_code(query: str, review: bool = False, llm: Any = None) -> dict:
    """يولّد كوداً من ``query`` ويكتبه على القرص مع دليل ``py_compile``.

    يعيد قاموساً يحوي ``build_id`` و``dir`` و``files`` و``proof`` و(اختيارياً)
    ``review``. يرفع ``CraftError`` عند فشل التوليد أو خرق بوابة الأمان.
    """
    question = (query or "").strip()[:800]
    if not question:
        raise CraftError("query مطلوب")

    llm = llm or _router()
    if llm is None:
        raise CraftError("LLM غير متاح")

    raw = llm.generate(
        prompt=(
            "المطلوب: " + question +
            "\nالقواعد: ملفات قليلة (1-6) مكتملة قابلة للتشغيل مباشرة؛ "
            "بايثون بلا اعتماديات خارجية؛ أضف README.md قصيراً يشرح التشغيل."
        ),
        system=_GEN_SYSTEM,
        temperature=0.2,
        max_tokens=MAX_TOKENS,
    )
    if isinstance(raw, dict) and not raw.get("ok", True):
        raise CraftError("LLM فشل: " + str(raw.get("error", ""))[:100])
    text = raw.get("text", "") if isinstance(raw, dict) else str(raw or "")

    parsed = _parse_files(text)
    total = 0
    for path, content in parsed:
        total += len(content.encode("utf-8"))
    if total > MAX_BYTES:
        raise CraftError("الحجم الإجمالي كبير جداً (>%d بايت)" % MAX_BYTES)

    build_id = "craft_" + str(int(time.time() * 1000))
    build_dir = os.path.join(builds_root(), build_id)
    os.makedirs(build_dir, exist_ok=True)

    proof: dict = {"files_written": 0, "py_compile": {}, "ok": True}
    listing: list = []
    for path, content in parsed:
        full = _safe_path(build_dir, path)
        os.makedirs(os.path.dirname(full) or build_dir, exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(content)
        proof["files_written"] += 1
        if full.endswith(".py"):
            cfile = os.path.join(tempfile.gettempdir(), str(abs(hash(full))) + ".pyc")
            try:
                py_compile.compile(full, cfile=cfile, doraise=True)
                proof["py_compile"][path] = "ok"
            except Exception as exc:
                proof["py_compile"][path] = ("error: " + type(exc).__name__)[:140]
                proof["ok"] = False
            finally:
                try:
                    os.remove(cfile)
                except OSError:
                    pass
        listing.append({"path": path, "bytes": len(content.encode("utf-8"))})

    with open(os.path.join(build_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(
            {"build_id": build_id, "query": question, "kind": "code",
             "files": listing, "proof": proof, "timestamp": time.time()},
            fh, ensure_ascii=False, indent=2,
        )

    return {
        "build_id": build_id,
        "dir": build_dir,
        "files": listing,
        "proof": proof,
        "review": _review(parsed, question) if (review and proof["ok"]) else None,
    }
