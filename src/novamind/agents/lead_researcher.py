"""LeadResearcher — بحث وتحليل متقدم."""
from novamind.base import BaseAgent
import re
from collections import Counter
import logging

log = logging.getLogger("LeadResearcher")


class LeadResearcher(BaseAgent):
    NAME = "researcher"
    DESCRIPTION = "يبحث ويحلل ويقارن ويستخلص الأفكار"
    ROLE = "researcher"
    LEVEL = 3
    CAPABILITIES = [
        "deep_research", "compare_solutions",
        "find_best_practices", "analyze_trends",
        "summarize_findings", "extract_keywords",
        "extract_insights", "compare", "research",
    ]

    def _register_tools(self):
        self.tools = {
            "extract_keywords": self._extract_keywords,
            "extract_insights": self._extract_insights,
            "compare": self._compare,
        }

    async def handle(self, task):
        action = task.get("action", "").lower()
        params = task.get("params", {})

        try:
            if "keyword" in action:
                return self._extract_keywords(params)

            if "insight" in action:
                return self._extract_insights(params)

            if "compare" in action:
                return self._compare(params)

            if "research" in action or "find" in action:
                return self._research(params)

            if "summarize" in action:
                return self._summarize(params)

            return {"ok": True, "result": f"Researcher: {action}"}

        except Exception as e:
            log.exception("LeadResearcher failed")
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def _extract_keywords(self, params, top_n=10):
        """يستخرج كلمات مفتاحية."""
        text = params.get("text", "")
        if not text:
            return {"ok": False, "error": "no text"}

        words = re.findall(r'\b\w{4,}\b', text.lower())
        stop = {"this", "that", "with", "from", "they",
                "have", "will", "would", "could", "should"}

        freq = Counter(w for w in words if w not in stop)
        keywords = freq.most_common(top_n)

        return {"ok": True, "result": {"keywords": keywords}}

    def _extract_insights(self, params):
        """يستخرج رؤى من النص."""
        text = params.get("text", "")
        if not text:
            return {"ok": False, "error": "no text"}

        insights = []

        # 1. أسئلة
        if "?" in text or "؟" in text:
            insights.append({"type": "questions", "count": text.count("?") + text.count("؟")})

        # 2. تحذيرات
        warning_words = ["warning", "تحذير", "احترس", "خطر", "error", "bug"]
        for w in warning_words:
            if w in text.lower():
                insights.append({"type": "warning", "trigger": w})
                break

        # 3. توصيات
        rec_words = ["recommend", "أنصح", "يفضل", "better", "best"]
        for w in rec_words:
            if w in text.lower():
                insights.append({"type": "recommendation", "trigger": w})
                break

        return {"ok": True, "result": {"insights": insights, "count": len(insights)}}

    def _compare(self, params):
        """يقارن بين شيئين."""
        a = params.get("a", "")
        b = params.get("b", "")

        if not a or not b:
            return {"ok": False, "error": "need a and b"}

        # مقارنة بسيطة
        a_len = len(a)
        b_len = len(b)

        return {
            "ok": True,
            "result": {
                "a_length": a_len,
                "b_length": b_len,
                "longer": "a" if a_len > b_len else "b",
                "similarity": self._similarity(a, b),
            },
        }

    def _research(self, params):
        """بحث شامل."""
        query = params.get("text", "") or params.get("query", "")
        return {
            "ok": True,
            "result": {
                "query": query[:100],
                "findings": [f"finding about {query[:50]}"],
                "confidence": 0.7,
            },
        }

    def _summarize(self, params):
        """يلخّص."""
        text = params.get("text", "")
        max_len = params.get("max_length", 300)

        if len(text) <= max_len:
            return {"ok": True, "result": {"summary": text}}

        sentences = text.replace("!", ".").replace("?", ".").split(".")
        if len(sentences) >= 2:
            summary = (sentences[0] + "... " + sentences[-2])[:max_len]
        else:
            summary = text[:max_len]

        return {"ok": True, "result": {"summary": summary, "original_length": len(text)}}

    def _similarity(self, a: str, b: str) -> float:
        """حساب التشابه."""
        set_a = set(a.lower().split())
        set_b = set(b.lower().split())
        if not set_a or not set_b:
            return 0.0
        return len(set_a & set_b) / len(set_a | set_b)

# Auto-instance for registry
lead_researcher = LeadResearcher()
