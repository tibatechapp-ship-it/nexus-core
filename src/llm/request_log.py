import datetime as _dt, json, os, tempfile
from pathlib import Path

SCHEMA_VERSION = 1
MAX_BYTES = 10 * 1024 * 1024
BACKUPS = 5
MIN_SAMPLE = 100
_ALIASES = {"high": "HIGH", "HIGH": "HIGH", "med": "MED", "medium": "MED", "MED": "MED", "MEDIUM": "MED", "low": "LOW", "LOW": "LOW"}


def _now():
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _path():
    ov = os.environ.get("NEXUS_REQUEST_LOG")
    if ov: return Path(ov).expanduser()
    try:
        d = Path(__file__).resolve().parents[2] / "data"
        d.mkdir(parents=True, exist_ok=True)
        return d / "request_log.jsonl"
    except OSError:
        return Path(tempfile.gettempdir()) / "nexus_request_log.jsonl"


def _max_bytes():
    raw = os.environ.get("NEXUS_REQUEST_LOG_MAX_BYTES")
    try: return max(1, int(raw)) if raw else MAX_BYTES
    except (ValueError, TypeError): return MAX_BYTES


def _rotate(p):
    try:
        for i in range(BACKUPS, 0, -1):
            src = p.with_name(p.name + (f".{i-1}" if i > 1 else ""))
            dst = p.with_name(p.name + f".{i}")
            if src.exists():
                if dst.exists(): dst.unlink()
                src.rename(dst)
    except OSError: pass


def record(priority, agent_id, outcome, reason=None):
    row = {"schema": SCHEMA_VERSION, "ts": _now(),
           "priority": _ALIASES.get(str(priority).lower(), "MED"),
           "agent_id": str(agent_id)[:120], "outcome": str(outcome)[:40]}
    if reason: row["reason"] = str(reason)[:200]
    try:
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.open("a", encoding="utf-8").write(json.dumps(row, ensure_ascii=False) + "\n")
        try:
            if p.stat().st_size >= _max_bytes(): _rotate(p)
        except OSError: pass
    except Exception: pass


def aggregate(window_days=7):
    if not isinstance(window_days, int) or window_days < 1: window_days = 7
    cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=window_days)
    counts = {p: 0 for p in ("HIGH", "MED", "LOW")}
    fails = total = 0
    try:
        p = _path()
        if p.exists():
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                if not line.strip(): continue
                try: row = json.loads(line)
                except json.JSONDecodeError: continue
                if not isinstance(row, dict): continue
                t = row.get("ts")
                if not isinstance(t, str): continue
                try: ts = _dt.datetime.fromisoformat(t.replace("Z", "+00:00"))
                except ValueError: continue
                if ts.tzinfo is None: ts = ts.replace(tzinfo=_dt.timezone.utc)
                if ts < cutoff: continue
                total += 1
                k = _ALIASES.get(str(row.get("priority", "")).lower())
                if k: counts[k] += 1
                if row.get("outcome") != "success": fails += 1
    except Exception: pass
    return {"total_requests": total, "by_priority": counts,
            "failure_pct": round((fails / total) * 100.0, 2) if total else 0.0,
            "high_pct": round((counts["HIGH"] / total) * 100.0, 2) if total else 0.0,
            "sample_sufficient": total >= MIN_SAMPLE, "sampled_at": _now()}
