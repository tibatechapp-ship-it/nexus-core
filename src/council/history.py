"""Council History — سجل قرارات."""
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

    def save(self, result, topic_id="", category=""):
        rec_id = "decision_" + str(int(time.time() * 1000))
        record = {
            "id": rec_id, "verdict": result.verdict,
            "score": result.score, "rounds": result.rounds,
            "timestamp": time.time(), "topic_id": topic_id,
            "category": category, "security_events": result.security_events,
        }
        try:
            with open(os.path.join(self.history_dir, rec_id + ".json"),
                      "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, indent=2, default=str)
        except Exception:
            pass

        rag = self._get_rag()
        if rag:
            summary = "[Council " + result.verdict.upper() + "] " + \
                      (topic_id or category or "decision") + \
                      ": score=" + str(round(result.score, 2))
            try:
                rag.remember(summary, doc_id=rec_id)
            except Exception:
                pass
        return rec_id

    def stats(self):
        files = [f for f in os.listdir(self.history_dir) if f.endswith(".json")]
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
            "total": len(files), "by_verdict": verdicts,
            "avg_score": sum(scores) / len(scores) if scores else 0,
            "avg_rounds": sum(rounds) / len(rounds) if rounds else 0,
        }

    def list_recent(self, n=10):
        files = sorted(
            [f for f in os.listdir(self.history_dir) if f.endswith(".json")],
            reverse=True
        )[:n]
        result = []
        for fn in files:
            try:
                with open(os.path.join(self.history_dir, fn), encoding="utf-8") as f:
                    result.append(json.load(f))
            except Exception:
                pass
        return result


_hist = None

def get_history():
    global _hist
    if _hist is None:
        _hist = CouncilHistory()
    return _hist
