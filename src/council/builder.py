"""Council Builder — يحوّل قرار المجلس إلى مخرجات ملموسة (Builder mode).

بعد أن يقرّر المجلس، يبني هذا المكوّن "حِزمة" قابلة للاستخدام داخل مجلد جلسة
منفصل: خطة (``PLAN.md``)، سجل القرار (``decision.json``)، وأي ملفات يقترحها
النموذج (نمط كود) مع بيان (``manifest.json``).

مبادئ التصميم:

* **بلا LLM → مخرَج حتمي**: نسخة الخطة تُبنى من نتيجة المجلس نفسها (حكم، ثقة،
  توصية) بلا أي نداء شبكة، فتعمل offline وقابلة للاختبار.
* **مع LLM → نمط كود**: يُطلب من النموذج JSON صارم (ملفات + خطوات)؛ أي فشل
  في التحليل يرجع للخطة الحتمية.
* **أمان الكتابة**: كل مسار يُقيَّد داخل مجلد البناء (لا ``..`` ولا مسار مطلق)،
  وللحد الأقصى حجم ملف ومجموعه.
* **دليل (proof)**: لكل ملف Python يُشغَّل ``py_compile`` — لا نعلن النجاح
  بلا تحقق قابل للملاحظة.
"""
from __future__ import annotations

import hashlib
import json
import os
import py_compile
import re
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from src.council.recommend import extract_recommendation

__all__ = [
    "BuildFile",
    "BuildResult",
    "Builder",
    "builds_root",
    "list_builds",
    "get_build",
]

ENV_BUILDS = "NEXUS_BUILDS"
DEFAULT_BUILDS_DIR = os.path.join(os.path.expanduser("~"), ".nexus", "data", "builds")

# مسار نسبي آمن: أحرف/أرقام/نقط/شرطة/شرطة سفلية/سلسلة مائلة
_SAFE_RE = re.compile(r"^[A-Za-z0-9._/\-]+$")


def builds_root() -> str:
    """جذر مجلدات البناء (``NEXUS_BUILDS`` أو ``~/.nexus/data/builds``)."""
    return os.environ.get(ENV_BUILDS) or DEFAULT_BUILDS_DIR


def _compose_blueprint_prompt(instructions: str, task: str) -> str:
    """يحقن معرفة المشروع (الطبقة 2) في برومبت البنّاء قبل نداء LLM.

    يسقط لبرومبت التعليمات + السؤال عند تعذّر طبقة المعرفة، فلا يتعطّل البناء أبدًا.
    """
    try:
        from src.knowledge import inject_into_prompt

        return inject_into_prompt("builder", task, instructions=instructions)
    except Exception:  # pragma: no cover - defensive: never break the build
        return f"{instructions}\n\nالسؤال: {task}"


def _get(obj: Any, name: str, default: Any = None) -> Any:
    value = getattr(obj, name, None)
    if value is None and isinstance(obj, dict):
        value = obj.get(name)
    return value if value is not None else default


def _safe_rel_path(path: str) -> Optional[str]:
    """يطبّع مساراً نسبياً أو يعيد ``None`` إن كان غير آمن."""
    raw = str(path or "").strip().replace("\\", "/")
    if not raw or len(raw) > 200:
        return None
    if raw.startswith("/") or raw.startswith("~"):
        return None
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    norm = "/".join(parts)
    if not _SAFE_RE.match(norm):
        return None
    return norm


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class BuildFile:
    """ملف واحد داخل حِزمة البناء."""

    path: str
    content: str

    @property
    def size(self) -> int:
        return len(self.content.encode("utf-8"))


@dataclass
class BuildResult:
    """نتيجة البناء الكاملة + دليل التحقق."""

    build_id: str
    title: str
    kind: str
    summary: str
    files: list = field(default_factory=list)
    dir: str = ""
    manifest_path: str = ""
    proof: dict = field(default_factory=dict)
    ok: bool = False


class Builder:
    """يبني مخرجات من قرار المجلس — حتمي offline، ونمط كود مع LLM."""

    MAX_FILES = 40
    MAX_FILE_BYTES = 200_000

    _CODE_HINTS = ("كود", "code", "برنامج", "سكربت", "script", "دالة", "function",
                   "api", "endpoint", "كلاس", "class", "ملف", "تطبيق", "app")

    _counter = 0

    def __init__(self, root: Optional[str] = None, llm: Any = None) -> None:
        self.root = root or builds_root()
        self.llm = llm

    # ────────────────────────── كشف النوع ──────────────────────────
    def detect_kind(self, question: str) -> str:
        q = (question or "").lower()
        return "code" if any(h in q for h in self._CODE_HINTS) else "plan"

    # ────────────────────── المخطّط الحتمي (offline) ─────────────────
    def _steps_for(self, verdict: str, recommendation: str) -> list:
        rec = recommendation or "(لا توصية مستخرجة)"
        if verdict == "approve":
            return [f"نفّذ التوصية: {rec}",
                    "أضف اختباراً يثبت النتيجة قبل الإعلان",
                    "وثّق القرار في السجل (history)"]
        if verdict == "reject":
            return ["لا تنفّذ هذه التوصية",
                    "سجّل أسباب الرفض صراحةً",
                    "اقترح بديلاً وأعد المداولة حوله"]
        return [f"راجع يدوياً: {rec}",
                "اجمع أدلة إضافية (أرقام/اختبارات)",
                "أعد المداولة بسياق أوضح"]

    def plan(self, question: str, result: Any) -> dict:
        """مخطّط حتمي من نتيجة المجلس — بلا LLM، صالح دائماً."""
        verdict = str(_get(result, "verdict", "unknown"))
        score = float(_get(result, "score", 0) or 0)
        consensus = bool(_get(result, "consensus", False))
        rounds = _get(result, "rounds", 0) or 0
        transcript = _get(result, "transcript", []) or []
        recommendation = extract_recommendation(transcript)
        title = (question or "قرار المجلس").strip().splitlines()[0][:80]

        plan_md = "\n".join([
            f"# {title}",
            "",
            f"> بُني من قرار المجلس — الحكم: **{verdict.upper()}** "
            f"({score * 100:.0f}%) — إجماع: {'نعم' if consensus else 'لا'} "
            f"— جولات: {rounds}",
            "",
            "## السؤال",
            (question or "").strip(),
            "",
            "## قرار المجلس",
            f"- الحكم: {verdict}",
            f"- الثقة: {score * 100:.0f}%",
            f"- التوصية: {recommendation or '(لا توصية)'}",
            "",
            "## الخطوات المقترحة",
        ] + [f"{i}. {s}" for i, s in enumerate(self._steps_for(verdict, recommendation), 1)] + [
            "",
            "## ملاحظة",
            "هذه خطة مبنية على قرار المجلس. عند توفّر مزوّد LLM يمكن توليد ملفات "
            "كود فعلية (Builder mode → kind=code).",
            "",
        ])

        decision_json = json.dumps({
            "query": question,
            "verdict": verdict,
            "score": score,
            "consensus": consensus,
            "rounds": rounds,
            "recommendation": recommendation,
        }, ensure_ascii=False, indent=2)

        return {
            "title": title,
            "kind": "plan",
            "summary": f"خطة بُنيت من قرار «{verdict}»" + (f" — التوصية: {recommendation}" if recommendation else ""),
            "steps": self._steps_for(verdict, recommendation),
            "files": [
                {"path": "PLAN.md", "content": plan_md},
                {"path": "decision.json", "content": decision_json},
            ],
        }

    # ─────────────────────── المخطّط من LLM ────────────────────────
    def _blueprint_prompt(self, question: str, result: Any) -> str:
        transcript = _get(result, "transcript", []) or []
        recommendation = extract_recommendation(transcript)
        verdict = _get(result, "verdict", "unknown")
        instructions = (
            "أنت «البنّاء» في مجلس قرارات. حوّل القرار إلى مخرجات ملموسة.\n"
            "أعد **JSON صارماً فقط** (بلا شرح ولا ```) بالشكل:\n"
            '{"title": "...", "kind": "code|plan|doc", "summary": "...", '
            '"steps": ["..."], "files": [{"path": "main.py", "content": "..."}]}\n\n'
            "قواعد: مسارات نسبية فقط بلا ``..``، ملفات نصية، لا أسرار، لا أوامر مدمّرة.\n\n"
            f"قرار المجلس: {verdict}\n"
            f"التوصية: {recommendation or '(لا توصية)'}"
        )
        return _compose_blueprint_prompt(instructions, question)

    def blueprint_from_llm(self, question: str, result: Any) -> Optional[dict]:
        """يطلب مخطّط JSON من النموذج؛ يعيد ``None`` عند أي فشل."""
        if not self.llm:
            return None
        try:
            raw = self.llm.generate(
                prompt=self._blueprint_prompt(question, result),
                system="أعد JSON صارماً فقط.",
                temperature=0.2,
                max_tokens=4000,
            )
        except Exception:
            return None
        if isinstance(raw, dict):
            text = raw.get("text", "") if raw.get("ok", True) else ""
        else:
            text = str(raw or "")
        return self.parse_blueprint(text)

    @staticmethod
    def parse_blueprint(text: str) -> Optional[dict]:
        """يحلّل JSON النموذج (يتحمّل ```fences```) ويرفض النتيجة غير الصالحة."""
        if not text:
            return None
        s = text.strip()
        # إزالة أسوار الكود إن وُجدت
        if s.startswith("```"):
            s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
            s = re.sub(r"\n?```\s*$", "", s).strip()
        start, end = s.find("{"), s.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            data = json.loads(s[start:end + 1])
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        files = data.get("files")
        if not isinstance(files, list):
            data["files"] = []
        return data

    # ─────────────────────────── البناء ────────────────────────────
    def build(self, question: str, result: Any, use_llm: bool = True) -> BuildResult:
        """يبني الحِزمة على القرص ويعيد النتيجة مع الدليل."""
        Builder._counter += 1
        build_id = f"build_{int(time.time() * 1_000_000)}_{Builder._counter}"
        build_dir = os.path.join(self.root, build_id)
        os.makedirs(build_dir, exist_ok=True)

        blueprint = None
        if use_llm:
            blueprint = self.blueprint_from_llm(question, result)
        if not blueprint:
            blueprint = self.plan(question, result)

        title = str(blueprint.get("title") or (question or "قرار").strip()[:80])
        kind = str(blueprint.get("kind") or "plan").strip().lower()
        summary = str(blueprint.get("summary") or "")
        steps = blueprint.get("steps") if isinstance(blueprint.get("steps"), list) else []

        # 1) ملفات النموذج (مسارات آمنة فقط)
        llm_files: dict = {}
        skipped: list = []
        raw_files = blueprint.get("files") if isinstance(blueprint.get("files"), list) else []
        for item in raw_files:  # type: ignore[union-attr]
            if isinstance(item, dict) and item.get("path"):
                rel = _safe_rel_path(item["path"])
                if rel is None:
                    skipped.append(str(item["path"]))
                    continue
                llm_files[rel] = str(item.get("content", ""))

        # 2) الملفات الإلزامية: سجل القرار دائماً + خطة إن لم يأتِ بها النموذج
        plan = self.plan(question, result)
        plan_content = next((f["content"] for f in plan["files"] if f["path"] == "PLAN.md"), "")
        essential: dict = {
            "decision.json": json.dumps({
                "query": question,
                "verdict": _get(result, "verdict", "unknown"),
                "score": float(_get(result, "score", 0) or 0),
                "consensus": bool(_get(result, "consensus", False)),
                "rounds": _get(result, "rounds", 0) or 0,
                "recommendation": extract_recommendation(_get(result, "transcript", []) or []),
                "steps": steps,
            }, ensure_ascii=False, indent=2),
        }
        if "PLAN.md" not in llm_files:
            essential["PLAN.md"] = plan_content

        # 3) الحد الأقصى: نترك دائماً مكاناً للملفات الإلزامية
        budget = max(0, self.MAX_FILES - len(essential))
        for rel in list(llm_files)[budget:]:
            skipped.append(rel)
            del llm_files[rel]

        # 4) الدمج — الملفات الإلزامية تطغى وتُضمن دائماً
        wanted = dict(llm_files)
        wanted.update(essential)

        # 5) الكتابة (مقيّدة داخل مجلد البناء)
        written: list = []
        kept: list = []
        real_root = os.path.realpath(build_dir)
        for rel, content in wanted.items():
            target = os.path.join(build_dir, rel)
            if not os.path.realpath(target).startswith(real_root + os.sep):
                skipped.append(rel)
                continue
            if len(content.encode("utf-8")) > self.MAX_FILE_BYTES:
                skipped.append(rel)
                continue
            os.makedirs(os.path.dirname(target) or build_dir, exist_ok=True)
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(content)
            written.append({"path": rel, "bytes": len(content.encode("utf-8")),
                            "sha256": _sha256(content)})
            kept.append(BuildFile(rel, content))

        # الدليل يُحسب بعد اكتمال كل الكتابات
        proof = self._prove(build_dir, written)

        manifest = {
            "build_id": build_id,
            "title": title,
            "kind": kind,
            "summary": summary,
            "steps": steps,
            "verdict": _get(result, "verdict", "unknown"),
            "files": written,
            "skipped": skipped,
            "proof": proof,
            "timestamp": time.time(),
        }
        manifest_path = os.path.join(build_dir, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2)

        return BuildResult(
            build_id=build_id, title=title, kind=kind, summary=summary,
            files=kept,
            dir=build_dir, manifest_path=manifest_path,
            proof=proof, ok=bool(proof.get("ok")) and bool(written),
        )

    def _prove(self, build_dir: str, written: list) -> dict:
        """دليل قابل للملاحظة: عدد الملفات + py_compile لكل ملف .py.

        يُترجم كل ملف إلى ``.pyc`` مؤقت خارج مجلد البناء حتى لا يترك
        ``py_compile`` أثراً (``__pycache__``) في المخرجات.
        """
        checks: dict = {}
        for item in written:
            rel = item["path"]
            if not rel.endswith(".py"):
                continue
            target = os.path.join(build_dir, rel)
            cfile = os.path.join(tempfile.gettempdir(), _sha256(rel) + ".pyc")
            try:
                py_compile.compile(target, cfile=cfile, doraise=True)
                checks[rel] = "ok"
            except Exception as exc:
                checks[rel] = f"error: {type(exc).__name__}"
            finally:
                try:
                    os.remove(cfile)
                except OSError:
                    pass
        ok = bool(written) and all(v == "ok" for v in checks.values())
        return {"files_written": len(written), "py_compile": checks, "ok": ok}


# ─────────────────────────── قراءة الحِزم ───────────────────────────

def list_builds(root: Optional[str] = None, n: int = 20) -> list:
    """أحدث الحِزم (من manifest.json) — الأحدث أولاً."""
    root = root or builds_root()
    if not os.path.isdir(root):
        return []
    entries = sorted(os.listdir(root), reverse=True)[:n]
    out = []
    for name in entries:
        manifest = os.path.join(root, name, "manifest.json")
        if not os.path.exists(manifest):
            continue
        try:
            with open(manifest, encoding="utf-8") as fh:
                data = json.load(fh)
            out.append({
                "build_id": data.get("build_id", name),
                "title": data.get("title", ""),
                "kind": data.get("kind", ""),
                "ok": bool(data.get("proof", {}).get("ok")),
                "files": len(data.get("files", [])),
                "timestamp": data.get("timestamp", 0),
            })
        except Exception:
            continue
    return out


def get_build(build_id: str, root: Optional[str] = None) -> Optional[dict]:
    """manifest حزمة معيّنة أو ``None``."""
    root = root or builds_root()
    safe = _safe_rel_path(build_id)
    if not safe or "/" in safe:
        return None
    manifest = os.path.join(root, safe, "manifest.json")
    if not os.path.exists(manifest):
        return None
    try:
        with open(manifest, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None
