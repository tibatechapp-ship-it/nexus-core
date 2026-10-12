"""Critic — يقيّم ردود الوكيل."""
import logging
from typing import Dict, Any

log = logging.getLogger("Critic")


class Critic:
    """ناقد يقيّم الردود على 5 أبعاد."""

    WEIGHTS = {
        "correctness": 0.35,
        "completeness": 0.25,
        "clarity": 0.15,
        "relevance": 0.15,
        "efficiency": 0.10,
    }

    ACCEPT_THRESHOLD = 0.85

    STOP_WORDS = {
        "اشرح", "وضح", "ما", "هي", "هو", "كيف", "لماذا", "ماذا",
        "؟", "?", "و", "أو", "the", "and", "or", "explain",
        "what", "how", "why", "is", "are", "of", "in", "on",
        "a", "an", "to", "for",
    }

    UNCERTAIN_PHRASES = [
        "لا أعرف", "لا أستطيع", "غير متأكد", "غير قادر", "لا يمكنني",
        "i don't know", "i cannot", "not sure", "i'm not sure",
    ]

    def evaluate(self, question: str, reply: str,
                 tool_results: list = None) -> Dict[str, Any]:
        """يقيّم رداً بدون LLM (heuristic)."""
        if not reply or len(reply.strip()) < 5:
            return {
                "score": 0.0,
                "issues": ["empty_reply"],
                "needs_improvement": True,
                "dimensions": {},
            }

        issues = []
        scores = {}

        # ═══ 1. Correctness ═══
        correctness = 1.0

        # ردود "لا أعرف"
        reply_lower = reply.lower()
        if any(w in reply_lower for w in self.UNCERTAIN_PHRASES):
            if tool_results:
                correctness -= 0.5
                issues.append("uncertain_with_tools")
            else:
                correctness -= 0.35
                issues.append("uncertain_reply")

        # ردود قصيرة جداً
        if len(reply.strip()) < 15:
            correctness -= 0.3
            issues.append("too_short_generic")

        scores["correctness"] = max(0.0, correctness)

        # ═══ 2. Completeness ═══
        completeness = 1.0

        # كشف أجزاء السؤال
        parts_raw = self._split_question(question)
        required_parts = max(1, len(parts_raw))

        if required_parts >= 2:
            # استخرج كلمات مفتاحية لكل جزء
            parts_keywords = []
            for part in parts_raw:
                kws = set()
                for w in part.split():
                    w_clean = w.strip("؟?.,،:").lower()
                    if len(w_clean) > 2 and w_clean not in self.STOP_WORDS:
                        kws.add(w_clean)
                if kws:
                    parts_keywords.append(kws)

            # استبعد الكلمات المشتركة بين كل الأجزاء
            if len(parts_keywords) >= 2:
                common = set.intersection(*parts_keywords)
                parts_keywords = [kws - common for kws in parts_keywords]
                # احتفظ فقط بالأجزاء غير الفارغة
                parts_keywords = [kws for kws in parts_keywords if kws]

            # احسب نسبة الأجزاء المُغطاة
            if parts_keywords:
                covered = sum(
                    1 for kws in parts_keywords
                    if any(kw in reply_lower for kw in kws)
                )
                coverage = covered / len(parts_keywords)
            else:
                coverage = 1.0

            # ═══ عقوبة = نسبة الأجزاء المفقودة × 2.5 ═══
            missing = 1.0 - coverage
            penalty = min(missing * 2.5, 1.0)
            completeness -= penalty

            if coverage >= 0.99:
                pass  # لا عقوبة
            elif coverage >= 0.75:
                issues.append(f"missing_parts_{missing:.0%}")
            else:
                issues.append(f"missing_parts_{missing:.0%}_major")

        scores["completeness"] = max(0.0, completeness)

        # ═══ 3. Clarity ═══
        clarity = 1.0
        if len(reply) > 5000:
            clarity -= 0.2
            issues.append("too_long")
        if reply.count("...") > 5:
            clarity -= 0.1
            issues.append("excessive_ellipsis")
        scores["clarity"] = max(0.0, clarity)

        # ═══ 4. Relevance ═══
        relevance = 1.0
        question_words = {
            w.strip("؟?.,،:").lower()
            for w in question.split()
            if len(w.strip("؟?.,،:")) > 2
            and w.strip("؟?.,،:").lower() not in self.STOP_WORDS
        }
        if question_words:
            overlap = sum(
                1 for w in question_words if w in reply_lower
            ) / len(question_words)
            if overlap < 0.2:
                relevance -= 0.3
                issues.append("low_relevance")
            elif overlap < 0.4:
                relevance -= 0.1
        scores["relevance"] = max(0.0, relevance)

        # ═══ 5. Efficiency ═══
        efficiency = 1.0
        if len(reply) > 2000:
            efficiency -= 0.2
            issues.append("verbose")
        scores["efficiency"] = max(0.0, efficiency)

        # ═══ الحساب النهائي ═══
        total = sum(
            scores[dim] * self.WEIGHTS[dim]
            for dim in self.WEIGHTS
        )
        total = round(total, 3)

        return {
            "score": total,
            "issues": issues,
            "needs_improvement": total < self.ACCEPT_THRESHOLD,
            "dimensions": scores,
        }

    def _split_question(self, question: str) -> list:
        """يقسّم السؤال إلى أجزاء حسب الروابط."""
        import re
        # فواصل: " و " / " and " / " أو " / " or "
        parts = re.split(r'\s+(?:و|and|أو|or)\s+', question)
        parts = [p.strip() for p in parts if p.strip()]
        return parts if parts else [question]


_singleton = None


def get_critic() -> Critic:
    """يرجع instance واحد."""
    global _singleton
    if _singleton is None:
        _singleton = Critic()
    return _singleton
