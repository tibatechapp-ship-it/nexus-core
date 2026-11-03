"""Live KPIs computed from the two append-only logs (M3.3).

مؤشرات حية فوق لوحة القراءة-فقط (مهمة M3.3): كل رقم مشتق حرفياً من سجلَّي
الأثر (``runs/trace.jsonl``) والبوابة (``runs/quality_gate.jsonl``) — لا تقدير
ولا حالة مخبأة. المساران قابلان للتوجيه بنفس متغيرات البيئة المعيارية
(``NEXUS_TRACE_PATH`` و``NEXUS_QUALITY_GATE_LOG``) فتبقى الاختبارات محكمة،
والسطور التالفة تُتخطى بصمت بدل أن تُسقط اللوحة.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from src.observability.trace import trace_path as default_trace_path

GATE_LOG_ENV = "NEXUS_QUALITY_GATE_LOG"
DEFAULT_GATE_LOG = Path("runs") / "quality_gate.jsonl"


def _gate_default_path() -> Path:
    env = os.environ.get(GATE_LOG_ENV)
    return Path(env) if env else DEFAULT_GATE_LOG


def _read_tail(path: Path | None, limit: int) -> list[dict]:
    """Last ``limit`` valid JSON objects of a JSONL file; missing = empty."""
    limit = max(int(limit), 0)
    if path is None or limit == 0 or not Path(path).exists():
        return []
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace")\
            .splitlines()
    except OSError:
        return []
    out: list[dict] = []
    for line in lines[-limit:]:
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _rate(flags: list[bool]) -> float | None:
    return round(sum(flags) / len(flags), 4) if flags else None


def _percentile(sorted_values: list[float], q: float) -> float | None:
    if not sorted_values:
        return None
    idx = min(len(sorted_values) - 1, max(0, round(q * (len(sorted_values) - 1))))
    return sorted_values[idx]


def _timing(events: list[dict]) -> dict:
    values = sorted(float(e["duration_ms"]) for e in events
                    if isinstance(e.get("duration_ms"), (int, float)))
    return {"p50_ms": _percentile(values, 0.50), "p95_ms": _percentile(values, 0.95)}


def _trace_kpis(path: Path | None, limit: int) -> dict:
    events = _read_tail(path, limit)
    by_agent: dict[str, int] = {}
    for e in events:
        agent = str(e.get("agent", "?"))
        by_agent[agent] = by_agent.get(agent, 0) + 1
    kpis = {
        "available": bool(events),
        "events": len(events),
        "ok_rate": _rate([e.get("outcome") == "ok" for e in events]),
        "by_agent": dict(sorted(by_agent.items(), key=lambda kv: -kv[1])),
    }
    kpis.update(_timing(events))
    return kpis


def _gate_kpis(path: Path | None, limit: int) -> dict:
    runs = _read_tail(path, limit)
    kpis = {
        "available": bool(runs),
        "runs": len(runs),
        "ok_rate": _rate([r.get("ok") is True for r in runs]),
    }
    kpis.update(_timing(runs))
    return kpis


def compute_kpis(trace_path: Path | str | None = None,
                 gate_path: Path | str | None = None,
                 limit: int = 500) -> dict:
    """KPIs over the last ``limit`` records of each log — numbers only."""
    limit = max(int(limit), 0)
    trace = _trace_kpis(Path(trace_path) if trace_path else default_trace_path(),
                        limit)
    gate = _gate_kpis(Path(gate_path) if gate_path else _gate_default_path(),
                      limit)
    return {
        "trace": trace,
        "gate": gate,
        "window": limit,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
