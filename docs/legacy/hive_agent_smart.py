#!/usr/bin/env python3
"""Hive Smart Agent 24/7."""
import asyncio, json, logging, subprocess, sys
from datetime import datetime
from pathlib import Path

# [FIXED PATH] Use relative imports or conftest.py instead
LOG_DIR = Path("/var/log/novamind")

# ═══ Reflection (Critic + Reflector) ═══
try:
    from hive.reflection import get_critic, get_reflector
    HAS_REFLECTION = True
except ImportError as e:
    HAS_REFLECTION = False
    _reflection_error = str(e)

LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_DIR / "smart_agent.log")],
)
log = logging.getLogger("SmartAgent")
PUBLIC = Path("/public")
CHECK_INTERVAL = 60
MAX_LLM_PER_HOUR = 60

stats = {"iterations": 0, "commits": 0, "pushes": 0,
         "test_runs": 0, "test_failures": 0,
         "llm_calls": 0, "fixes": 0}

_llm_cache = {}
_last_commit = None
_consecutive_failures = 0
_MAX_FAILURES = 3


def run_cmd(cmd, timeout=30):
    lower = cmd.lower()
    if "force" in lower and "push" in lower: return -1, "", "blocked"
    if "reset --hard" in lower: return -1, "", "blocked"
    if "rm -rf" in lower: return -1, "", "blocked"
    try:
        r = subprocess.run(cmd, shell=True, cwd=str(PUBLIC),
                          capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"


def check_secrets(text):
    return any(p in text for p in ["gsk_", "ghp_", "sk-", "AKIA", "AIza", "AQ.Ab"])


async def git_guardian():
    # ═══ فحص القفل اليدوي ═══
    if is_manual_lock_active():
        log.debug("🔒 Manual lock active — skipping autosave")
        return {"changed": 0, "ahead": 0, "behind": 0, "locked": True}

    _, changed, _ = run_cmd("git status --porcelain")
    cnt = len([l for l in changed.split("\n") if l.strip()])
    if cnt > 0:
        run_cmd("git add -A")
        ts = datetime.now().strftime("%H:%M:%S")
        code, _, _ = run_cmd(f'git commit -m "chore(agent): autosave {ts}"')
        if code == 0:
            stats["commits"] += 1
            log.info(f"committed {cnt} files")
    _, a_str, _ = run_cmd("git rev-list --count origin/main..HEAD")
    a = int(a_str) if a_str.isdigit() else 0
    if a > 0:
        code, _, _ = run_cmd("git push", timeout=60)
        if code == 0:
            stats["pushes"] += 1
            log.info(f"pushed {a}")
    _, b_str, _ = run_cmd("git rev-list --count HEAD..origin/main")
    b = int(b_str) if b_str.isdigit() else 0
    if b > 0:
        run_cmd("git pull --rebase", timeout=60)
        log.info(f"pulled {b}")
    return {"changed": cnt, "ahead": a, "behind": b}


async def test_runner():
    global _last_commit
    _, cur, _ = run_cmd("git rev-parse HEAD")
    if cur == _last_commit or not cur: return None
    _last_commit = cur
    stats["test_runs"] += 1
    log.info(f"Testing {cur[:8]}...")
    code, out, _ = run_cmd(
        "python3 -m pytest tests/ -q --no-header --tb=line 2>&1 | tail -3",
        timeout=180)
    if "passed" in out and "failed" not in out:
        log.info("✅ tests ok")
        return {"passed": True, "summary": out}
    else:
        stats["test_failures"] += 1
        log.error(f"❌ {out[:200]}")
        return {"passed": False, "summary": out}


async def _raw_llm_call(question):
    """يستدعي LLM بدون Critic — للاستخدام الداخلي."""
    from hive.agents import get_tool_agent
    agent = get_tool_agent()
    r = await asyncio.wait_for(agent.chat(question), timeout=60)
    if r.get("ok"):
        return r["reply"]
    raise RuntimeError(r.get("error", "LLM error"))


async def ask_llm(question, use_critic=True):
    """يستدعي LLM مع تحسين تلقائي عبر Critic."""
    if stats["llm_calls"] >= MAX_LLM_PER_HOUR:
        return "[quota]"
    key = question[:100]
    if key in _llm_cache:
        return _llm_cache[key]
    stats["llm_calls"] += 1

    try:
        raw_reply = await _raw_llm_call(question)
    except Exception as e:
        return f"[LLM: {str(e)[:50]}]"

    # ═══ Critic Layer ═══
    if use_critic and HAS_REFLECTION and not raw_reply.startswith("["):
        try:
            critic = get_critic()
            critique = critic.evaluate(question, raw_reply)

            if critique["needs_improvement"]:
                log.info(
                    f"🔄 Critic: score={critique['score']:.2f} "
                    f"issues={critique['issues']}"
                )
                stats["fixes"] += 1

                reflector = get_reflector()
                result = await reflector.improve(
                    question, raw_reply, _raw_llm_call
                )

                if result.get("ok") and result.get("final_reply"):
                    log.info(
                        f"✅ Improved: {critique['score']:.2f} → "
                        f"{result['final_score']:.2f} "
                        f"(iter={result['iterations']})"
                    )
                    raw_reply = result["final_reply"]
        except Exception as e:
            log.warning(f"Critic layer failed: {e}")

    _llm_cache[key] = raw_reply
    return raw_reply


async def auto_fixer(test_result):
    if not test_result or test_result.get("passed"): return None
    summary = test_result.get("summary", "")
    if "ModuleNotFoundError" in summary or "No module named" in summary:
        _, dirs, _ = run_cmd("find hive -type d -not -name __pycache__")
        for d in dirs.split("\n"):
            if d and not Path(PUBLIC, d, "__init__.py").exists():
                Path(PUBLIC, d, "__init__.py").touch()
                stats["fixes"] += 1
        return "added __init__.py"
    if "No such file" in summary:
        for d in ["memory/providers", "memory/vector_store",
                  "memory/knowledge_graph", "memory/projects"]:
            Path(PUBLIC, d).mkdir(parents=True, exist_ok=True)
            Path(PUBLIC, d, ".gitkeep").touch()
        stats["fixes"] += 1
        return "created dirs"
    if "Error" in summary or "FAILED" in summary:
        answer = await ask_llm(f"فشل pytest:\n```\n{summary[:800]}\n```\nاقترح حل.")
        with open(LOG_DIR / "llm_suggestions.log", "a") as f:
            f.write(f"\n[{datetime.now().isoformat()}]\n{answer}\n")
        return "logged LLM"
    return None




# ═══ State persistence ═══
STATE_FILE = LOG_DIR / "smart_agent_state.json"


def save_state():
    """يحفظ state."""
    try:
        STATE_FILE.write_text(json.dumps(stats, indent=2))
    except Exception as e:
        log.warning(f"save_state failed: {e}")


def load_state():
    """يقرأ state."""
    global stats
    try:
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text())
            # احتفظ بالـ started_at الأصلي
            started = stats.get("started_at")
            stats.update(data)
            if started:
                stats["started_at"] = started
    except Exception as e:
        log.warning(f"load_state failed: {e}")




# ═══ Graceful shutdown ═══
import signal


def _shutdown_handler(sig, frame):
    log.info(f"Signal {sig} received — graceful shutdown")
    save_state()
    log.info("✅ State saved. Exiting.")
    sys.exit(0)


signal.signal(signal.SIGTERM, _shutdown_handler)
signal.signal(signal.SIGINT, _shutdown_handler)



# ═══ Manual lock check ═══
MANUAL_LOCK = Path("/public/.git_manual_lock")


def is_manual_lock_active() -> bool:
    """يتحقق إن كان المستخدم يعمل يدوياً."""
    return MANUAL_LOCK.exists()

async def main_loop():
    load_state()
    log.info("══════════════════════════════════")
    log.info("🤖 Smart Agent started")
    if stats.get("iterations", 0) > 0:
        log.info(f"📊 Resumed — {stats['iterations']} iterations done")
    log.info("══════════════════════════════════")
    global _consecutive_failures
    while True:
        stats["iterations"] += 1
        i = stats["iterations"]
        try:
            gs = await git_guardian()
            tr = await test_runner()
            if tr and not tr.get("passed"):
                _consecutive_failures += 1
                await auto_fixer(tr)
                if _consecutive_failures >= _MAX_FAILURES:
                    log.error(f"🚨 {_MAX_FAILURES} failures — STOP")
                    break
            else:
                _consecutive_failures = 0
            if i % 5 == 0:
                locked = " 🔒" if gs.get("locked") else ""
                log.info(f"[{i}] c={gs['changed']} a={gs['ahead']} "
                         f"b={gs['behind']} llm={stats['llm_calls']} "
                         f"fixes={stats['fixes']}{locked}")
        except Exception as e:
            log.exception(f"iter {i}: {e}")
        await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        log.info("stopped")
