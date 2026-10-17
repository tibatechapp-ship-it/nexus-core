"""Knowledge Base — الطبقة المشتركة (الذاكرة الساخنة) لكل الوكلاء.

الطبقة 2 من نموذج التدريب: معارف المشروع تعيش في مكان واحد، تُقرأ وتُبحث
وتُحقن في تعليمات الوكيل **قبل** أي مهمة — تماماً كما يُحمَّل ``AGENTS.md``
تلقائياً في كل جلسة لـ zyvo.

المصدران (الأخير يتقدّم عند تساوي الاسم):
    * بذرة المستودع  ``<repo>/knowledge/*.md``             (مرجعي، مُلتزَم)
    * تجاوز المستخدم ``~/.config/nexus/knowledge/*.md``    (خاص بالمستخدم)

كل وحدة معيارية فقط (stdlib) — يعمل على الهاتف بلا إضافات.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

__all__ = [
    "KnowledgeDoc",
    "KnowledgeBase",
    "KB_DIR",
    "SEED_DIR",
    "DEFAULT_LIMIT",
    "UNIVERSAL_DOCS",
    "normalize_token",
    "tokenize",
    "parse_front_matter",
    "get_knowledge_base",
    "reset_knowledge_base",
]

KB_DIR = Path.home() / ".config" / "nexus" / "knowledge"
SEED_DIR = Path(__file__).resolve().parents[2] / "knowledge"
DEFAULT_LIMIT = 4

#: الوثائق العامّة التي تُحقن لكل وكيل — ما هو المشروع، وكيف نعمل.
UNIVERSAL_DOCS: Tuple[str, ...] = ("nexus-core", "conventions")

#────────────────────────────── تنظيف وتقطيع ──────────────────────────────#

#: حركات التشكيل + التطويل تُزال قبل المقارنة.
_DIACRITICS = re.compile("[\u064b-\u0652\u0640]")
_TOKEN_RE = re.compile(r"[0-9a-z\u0600-\u06ff]+")

#: كلمات وقف عربية/إنجليزية تُستبعد حتى لا تُرجّح الترتيب بلا معنى.
_STOPWORDS = frozenset(
    """
    a an the and or of to in on for with is are was were be been by as at it
    this that these those from not no any all if then else do does did can
    من في على عن الى إلى مع هو هي هم هن هذا هذه ذلك تلك التي الذي كل بعض غير
    لا ما هل ثم او أو و يا كان تكون يكون ان أن إن قد لقد عند لدى به له لها
    """.split()
)

#: مفاتيح الـ front-matter المسموحة (غيرها يُتجاهل).
_META_KEYS = frozenset({"title", "category", "tags", "pinned"})

#: القيم التي تعني "نعم" للحقل ``pinned``.
_TRUE = frozenset({"true", "yes", "1", "on", "نعم", "صح"})


def normalize_token(token: str) -> str:
    """يوحّد شكل الكلمة: حالة صغيرة، بلا تشكيل، بألف/ياء/تاء موحّدة."""
    text = token.lower()
    text = _DIACRITICS.sub("", text)
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي").replace("ة", "ه")
    return text


def tokenize(text: str) -> List[str]:
    """يقطّع النص إلى كلمات مطبّعة (بلا كلمات الوقف).

    يُصغَّر النص **قبل** التطابق لأن ``_TOKEN_RE`` يغطي الحروف الصغيرة فقط —
    وإلا سقط أول حرف كبير من كل كلمة (``Rules`` → ``ules``).
    """
    out: List[str] = []
    for match in _TOKEN_RE.finditer(text.lower()):
        word = normalize_token(match.group(0))
        if word and word not in _STOPWORDS:
            out.append(word)
    return out


def parse_front_matter(text: str) -> Tuple[Dict[str, str], str]:
    """يفصل كتلة ``---`` العلوية عن المتن. يعيد (الميتاداتا، المتن)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    raw = text[3:end]
    body = text[end + 4 :]
    meta: Dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        if key in _META_KEYS:
            meta[key] = value.strip()
    return meta, body.lstrip("\n")


def _is_true(value: str) -> bool:
    """يقرأ حقل boolean من نص الـ front-matter."""
    return value.strip().lower() in _TRUE


def _first_heading(text: str) -> str:
    """أول عنوان ``#`` في المتن، وإلا أول سطر غير فارغ."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
        if stripped:
            return stripped
    return ""


#────────────────────────────────── الوثيقة ──────────────────────────────────#


@dataclass(frozen=True)
class KnowledgeDoc:
    """وثيقة معرفة واحدة (ملف markdown)."""

    name: str
    title: str
    content: str
    path: Path
    category: str = "general"
    tags: Tuple[str, ...] = ()
    pinned: bool = False

    @property
    def tokens(self) -> List[str]:
        """كلمات العنوان + الوسوم (وزن أعلى في البحث) والدسم مجتمعة."""
        return tokenize(self.title) + tokenize(" ".join(self.tags))

    def to_dict(self) -> Dict[str, Any]:
        """تمثيل JSON آمن (بلا محتوى كامل — حجم فقط)."""
        return {
            "name": self.name,
            "title": self.title,
            "category": self.category,
            "tags": list(self.tags),
            "pinned": self.pinned,
            "path": str(self.path),
            "chars": len(self.content),
        }


def _doc_from_path(path: Path) -> KnowledgeDoc:
    """يبني وثيقة من ملف على القرص."""
    text = path.read_text(encoding="utf-8")
    meta, body = parse_front_matter(text)
    title = meta.get("title") or _first_heading(body) or path.stem
    raw_tags = meta.get("tags", "")
    tags = tuple(t.strip() for t in raw_tags.split(",") if t.strip())
    return KnowledgeDoc(
        name=path.stem,
        title=title,
        content=body.strip(),
        path=path,
        category=meta.get("category", "general"),
        tags=tags,
        pinned=_is_true(meta.get("pinned", "")),
    )


#────────────────────────────────── القاعدة ──────────────────────────────────#


class KnowledgeBase:
    """قاعدة معرفة المشروع: قراءة، بحث، واختيار وثائق لوكيل.

    ``seed_dir`` = بذرة المستودع (المرجع)، ``user_dir`` = تجاوز المستخدم
    (**يتقدّم** عند تساوي الاسم).
    """

    def __init__(
        self,
        seed_dir: Path = SEED_DIR,
        user_dir: Path = KB_DIR,
        *,
        create: bool = True,
    ) -> None:
        self.seed_dir = Path(seed_dir)
        self.user_dir = Path(user_dir)
        if create:
            self.user_dir.mkdir(parents=True, exist_ok=True)
        self._docs: Optional[Dict[str, KnowledgeDoc]] = None

    #── الاكتشاف والتخزين المؤقت ──#

    def _discover(self) -> Dict[str, KnowledgeDoc]:
        """يبني خريطة الاسم ← وثيقة (تجاوز المستخدم يفوز عند التصادم)."""
        found: Dict[str, KnowledgeDoc] = {}
        for source in (self.seed_dir, self.user_dir):
            if not source.is_dir():
                continue
            for path in sorted(source.glob("*.md")):
                found[path.stem] = _doc_from_path(path)
        return found

    def _cache(self) -> Dict[str, KnowledgeDoc]:
        """التخزين المؤقت (يُبنى مرة واحدة حتى ``refresh``)."""
        if self._docs is None:
            self._docs = self._discover()
        return self._docs

    def refresh(self) -> None:
        """يسقط التخزين المؤقت (بعد تعديل الملفات على القرص)."""
        self._docs = None

    #── القراءة ──#

    def list_docs(self) -> List[str]:
        """أسماء الوثائق المتاحة مرتّبة."""
        return sorted(self._cache())

    def all_docs(self) -> List[KnowledgeDoc]:
        """كل الوثائق مرتّبة بالاسم."""
        cache = self._cache()
        return [cache[name] for name in sorted(cache)]

    def load(self, name: str) -> Optional[KnowledgeDoc]:
        """وثيقة بالاسم، أو ``None`` إن لم توجد."""
        return self._cache().get(name)

    def pinned(self) -> List[KnowledgeDoc]:
        """الوثائق المُثبّتة (تُحقن دائماً)."""
        return [doc for doc in self.all_docs() if doc.pinned]

    #── البحث ──#

    def _score(self, doc: KnowledgeDoc, query_tokens: Sequence[str]) -> float:
        """تطابق: العنوان/الوسوم بوزن 2، المتن بوزن 1.

        لا حاجة لحارس لاستعلام فارغ: ``search`` لا ينادي ``_score`` إلا
        بكلمات غير فارغة، ومجموعة فارغة تُنتج تقاطعاً صفرياً = 0.0.
        """
        wanted = set(query_tokens)
        head = set(doc.tokens)
        body = set(tokenize(doc.content))
        return 2.0 * len(wanted & head) + len(wanted & body)

    def search(self, query: str, limit: int = 5) -> List[KnowledgeDoc]:
        """أعلى ``limit`` وثيقة صلة بالاستعلام (روابط فقط > 0)."""
        tokens = tokenize(query)
        if not tokens or limit <= 0:
            return []
        scored: List[Tuple[float, str, KnowledgeDoc]] = []
        for doc in self.all_docs():
            score = self._score(doc, tokens)
            if score > 0:
                scored.append((score, doc.name, doc))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [doc for _, _, doc in scored[:limit]]

    #── الاختيار والحقن ──#

    def select(
        self,
        agent_id: str,
        task: str = "",
        limit: int = DEFAULT_LIMIT,
        category: str = "",
    ) -> List[KnowledgeDoc]:
        """وثائق الوكيل مرتّبة: العامّة، فالمُثبّتة، فوثيقة الفئة، فالأعلى صلة.

        الترتيب هو الأولوية: أهمّ ما يُحقَن دائماً في المقدّمة (ما هو المشروع
        وكيف نعمل)، ثم وثيقة فئة الوكيل، ثم ما تطلبه المهمّة فعلاً.
        """
        if limit <= 0:
            return []
        chosen: List[KnowledgeDoc] = []
        seen: Set[str] = set()

        def push(doc: Optional[KnowledgeDoc]) -> None:
            if doc is not None and doc.name not in seen:
                chosen.append(doc)
                seen.add(doc.name)

        for name in UNIVERSAL_DOCS:
            push(self.load(name))
        for doc in self.pinned():
            push(doc)
        push(self.category_doc(agent_id, category))
        haystack = f"{agent_id} {task}".strip()
        for doc in self.search(haystack, limit=limit + len(seen)):
            if len(chosen) >= limit:
                break
            push(doc)
        return chosen[:limit]

    def category_doc(
        self, agent_id: str, category: str = ""
    ) -> Optional[KnowledgeDoc]:
        """وثيقة فئة الوكيل: مطابقة الفئة أوّلًا، ثم الاسم أو الوسوم.

        ``category`` صريحة (مجموعة الوكيل) وإلا نستعمل ``agent_id`` نفسه، فيعمل
        الاستدعاء البسيط ``for_agent("coder")`` بلا أي إعداد إضافي.
        """
        for key in (category, agent_id):
            wanted = key.strip().lower()
            if not wanted:
                continue
            for doc in self.all_docs():
                if doc.category.lower() == wanted:
                    return doc
            for doc in self.all_docs():
                if doc.name.lower() == wanted:
                    return doc
                if any(tag.lower() == wanted for tag in doc.tags):
                    return doc
        return None

    def render(self, docs: Sequence[KnowledgeDoc]) -> str:
        """يُصيغ الوثائق ككتلة نصية جاهزة للحقن في تعليمات الوكيل."""
        if not docs:
            return ""
        names = ", ".join(doc.name for doc in docs)
        parts = [
            "### قاعدة المعرفة المشتركة (Knowledge Base)",
            f"<!-- docs: {names} -->",
        ]
        for doc in docs:
            parts.append("")
            parts.append(f"#### {doc.title}  ·  {doc.name}")
            parts.append(doc.content)
        return "\n".join(parts)

    def for_agent(
        self,
        agent_id: str,
        task: str = "",
        limit: int = DEFAULT_LIMIT,
        category: str = "",
    ) -> str:
        """كتلة المعرفة الجاهزة لوكيل: عامّة (nexus-core + conventions) + فئته + المهمّة."""
        return self.render(self.select(agent_id, task, limit, category))

    #── الإحصاء ──#

    def stats(self) -> Dict[str, Any]:
        """ملخّص: عدد الوثائق، الفئات، المُثبّتة، والمصادر."""
        docs = self.all_docs()
        categories: Dict[str, int] = {}
        for doc in docs:
            categories[doc.category] = categories.get(doc.category, 0) + 1
        return {
            "docs": len(docs),
            "categories": categories,
            "pinned": sum(1 for doc in docs if doc.pinned),
            "sources": [str(self.seed_dir), str(self.user_dir)],
        }


_BASE: Optional[KnowledgeBase] = None


def get_knowledge_base() -> KnowledgeBase:
    """النسخة العملية الواحدة (singleton)."""
    global _BASE
    if _BASE is None:
        _BASE = KnowledgeBase()
    return _BASE


def reset_knowledge_base() -> None:
    """يُصفّر الـ singleton (للاختبارات وإعادة التحميل)."""
    global _BASE
    _BASE = None
