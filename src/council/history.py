"""Council History — سجل قرارات مع محتوى كامل."""
import os, sys, json, time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))


class CouncilHistory:
    def __init__(self, history_dir=None):
        self.history_dir = history_dir or os.path.expanduser("~/.nexus/data/council_history")
        os.makedirs(self.history_dir, exist_ok=True)
        self._rag = None

    def _get_rag(self):
        if self._rag is None:
            try:
                from src.memory.agent_rag_bridge import get_bridge
                self._rag = get_bridge()
            except Exception:
                pass
        return self._rag

    _counter = 0

    def save(self, result, topic_id="", category="", query=""):
        """يحفظ قراراً كاملاً مع السؤال والـ transcript."""
        CouncilHistory._counter += 1
        rec_id = f"decision_{int(time.time() * 1_000_000)}_{CouncilHistory._counter}"

        # استخراج دفاعي
        def _get(name, default=None):
            v = getattr(result, name, None)
            if v is None and isinstance(result, dict):
                v = result.get(name)
            return v if v is not None else default

        record = {
            "id": rec_id,
            "query": query or _get("_query", "") or _get("query", ""),
            "verdict": _get("verdict", "unknown"),
            "score": float(_get("score", 0) or 0),
            "rounds": int(_get("rounds", 0) or 0),
            "consensus": bool(_get("consensus", False)),
            "reasoning": _get("reasoning", ""),
            "transcript": _get("transcript", []) or [],
            "topic_id": topic_id or _get("topic_id", ""),
            "category": category,
            "security_events": _get("security_events", []) or [],
            "timestamp": time.time(),
        }

        try:
            with open(os.path.join(self.history_dir, rec_id + ".json"),
                      "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            print("[History] خطأ الحفظ: " + str(e))

        # RAG summary — single source of truth, rich format (v1.7.0)
        rag = self._get_rag()
        if rag:
            v = str(record["verdict"] or "unknown").upper()
            s = float(record.get("score", 0) or 0)
            consensus = " | consensus" if record.get("consensus") else ""
            q_preview = (record["query"] or "")[:150]
            summary = "[Council %s | score=%.0f%%%s] %s" % (v, s * 100, consensus, q_preview)
            try:
                rag.remember(summary, doc_id=rec_id)
            except Exception:
                pass
        return rec_id

    def get_full(self, rec_id):
        """استرجاع قرار كامل (مع transcript)."""
        path = os.path.join(self.history_dir, rec_id + ".json")
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def stats(self):
        try:
            files = [f for f in os.listdir(self.history_dir) if f.endswith(".json")]
        except FileNotFoundError:
            return {"total": 0}
        if not files:
            return {"total": 0}
        verdicts = {"approve": 0, "reject": 0, "human_review": 0}
        scores, rounds = [], []
        for fn in files:
            try:
                with open(os.path.join(self.history_dir, fn), encoding="utf-8") as f:
                    r = json.load(f)
                    v = r.get("verdict", "unknown")
                    if v in verdicts:
                        verdicts[v] += 1
                    scores.append(r.get("score", 0))
                    rounds.append(r.get("rounds", 0))
            except Exception:
                pass
        return {
            "total": len(files),
            "by_verdict": verdicts,
            "avg_score": sum(scores) / len(scores) if scores else 0,
            "avg_rounds": sum(rounds) / len(rounds) if rounds else 0,
        }

    def list_recent(self, n=10):
        try:
            files = sorted(
                [f for f in os.listdir(self.history_dir) if f.endswith(".json")],
                reverse=True
            )[:n]
        except FileNotFoundError:
            return []
        result = []
        for fn in files:
            try:
                with open(os.path.join(self.history_dir, fn), encoding="utf-8") as f:
                    r = json.load(f)
                    result.append({
                        "id": r.get("id"),
                        "query": (r.get("query") or "")[:100],
                        "verdict": r.get("verdict"),
                        "score": r.get("score"),
                        "topic_id": r.get("topic_id", ""),
                        "timestamp": r.get("timestamp", 0),
                    })
            except Exception:
                pass
        return result


_hist = None

def get_history():
    global _hist
    if _hist is None:
        _hist = CouncilHistory()
    return _hist
