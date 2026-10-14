import io, sys
PATH = "src/council/rag_bridge.py"
src = io.open(PATH, encoding="utf-8").read()

if "_past_hint" in src:
    print("ALREADY_APPLIED")
    sys.exit(1)

# ── 1) دالة مشتركة: كلمات توقف + إطار مرجعي ──
METHOD = r'''    def _past_hint(self, question):
        """قرارات سابقة مشابهة (بعد إزالة كلمات التوقف) — مرجعية فقط، ليست حكماً."""
        try:
            from src.council.history import get_history
            STOP = {"هل", "نستخدم", "نضيف", "نعتمد", "نحذف", "نستبدل", "نرفع", "ندفع",
                    "نعطّل", "أم", "او", "أو", "في", "من", "على", "عن", "ما", "هو", "هي",
                    "لا", "أن", "ان", "إن", "إلى", "الى", "هذا", "هذه", "ذلك", "تلك",
                    "استخدام", "يفضل", "افضل", "الأفضل", "الافضل", "نعم", "كيف",
                    "لماذا", "متى", "ايهما", "أيهما", "لمشروعنا", "المشروع", "؟"}
            q_words = {w for w in question.lower().split() if w not in STOP}
            if len(q_words) < 2:
                return ""
            recent = get_history().list_recent(n=30) or []

            def _fld(rec, name, default=None):
                if isinstance(rec, dict):
                    return rec.get(name, default)
                return getattr(rec, name, default)

            scored = []
            for rec in recent:
                rq = (_fld(rec, "query", "") or "").lower()
                r_words = {w for w in rq.split() if w not in STOP}
                overlap = len(q_words & r_words)
                if overlap >= 2:
                    scored.append((overlap, rec))
            scored.sort(key=lambda x: -x[0])
            top = scored[:3]
            if not top:
                return ""
            lines = ["--- قرارات سابقة مشابهة (مرجعية فقط - ليست حكماً) ---",
                     "ابدأ منها إن كانت حججها أقوى، وخالفها صراحة بحجة أقوى إن وُجدت."]
            for _, rec in top:
                v = str(_fld(rec, "verdict", "?") or "?").upper()
                s = float(_fld(rec, "score", 0) or 0)
                rq = (_fld(rec, "query", "") or "")[:80]
                lines.append("- %s (ثقة %.0f%%): %s" % (v, s * 100, rq))
            return "\n" + "\n".join(lines) + "\n----------------------"
        except Exception:
            return ""

'''
anchor = "    def deliberate_with_memory"
if anchor not in src:
    print("ANCHOR_NOT_FOUND")
    sys.exit(1)
src = src.replace(anchor, METHOD + anchor, 1)

# ── 2) استبدال كتلة v1.5.3 القديمة بنداء الدالة ──
start = src.find("        # RECALL PAST SIMILAR DECISIONS (v1.5.3)")
end_txt = '        aug_context = (context + "\\n\\n" + past_hint).strip() if past_hint else context'
j = src.find(end_txt)
if start == -1 or j == -1 or j < start:
    print("RECALL_BLOCK_NOT_FOUND start=%s j=%s" % (start, j))
    sys.exit(1)
src = src[:start] + (
    '        past_hint = self._past_hint(question)\n'
    '        aug_context = (context + "\\n\\n" + past_hint).strip() if past_hint else context'
) + src[j + len(end_txt):]

# ── 3) حقن past_hint في مسار الويب (streaming) ──
stream_anchor = "        result = self.engine.deliberate(question, context, on_event=emit)"
INJ = (
    "        # تعلّم دائري في مسار الويب (v1.5.4)\n"
    "        past_hint = self._past_hint(question)\n"
    "        if past_hint:\n"
    "            context = context + chr(10) + past_hint\n"
    "            emit(\"status\", {\"phase\": \"past\", \"message\": \"قرارات سابقة مشابهة: حُقنت\"})\n\n"
)
if stream_anchor not in src:
    print("STREAM_ANCHOR_NOT_FOUND")
    sys.exit(1)
src = src.replace(stream_anchor, INJ + stream_anchor, 1)

io.open(PATH, "w", encoding="utf-8").write(src)
print("PATCH_154_OK")
