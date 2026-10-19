"""Hyper-Agent 2.0 — autonomous workflow engine (Day 1).

WHY this module exists: it is the runtime that ``hyper_app/routers/agent.py``
imports at module load (``from hyper_agent import autonomous_workflow_hyper``).
Until this file exists, ``POST /api/agent/start`` cannot even be imported.

Bug fixes baked in at birth (no legacy to patch — built this way on purpose):
  BUG-1  prune replaces ``state["history"]`` instead of appending a duplicate
  BUG-2  ollama ``num_predict=4000`` (lives in ``connectors/ollama.py``)
  BUG-3  ``detect_stall`` → ``status="stalled"`` after 3 identical non-DONE/ERROR
  BUG-4  stored history drops ``raw_result`` (only the parsed view is kept)
  BUG-5  ``last_parse_error`` counter is fed back into the next prompt
  BUG-6  sandbox uses ``preexec_fn`` + ``RLIMIT_CPU/FSIZE/NPROC`` (Termux-safe)
  BUG-7  ``run_code_sync``/``run_tests_sync`` use ``sys.executable``
  BUG-8  ``verify_goal`` gates DONE → ``status="verify_fail"`` if unmet
  BUG-9  README delivery filenames use ``-`` not ``_`` (doc concern, not code)

Design notes:
- The ollama connector ignores ``system_prompt`` (its ``generate`` body never
  reads it). For local runs we therefore fold system context into the user
  prompt ourselves so the model still sees the instruction.
- History entries are small dicts (``role``/``content``/``action``); we never
  store the raw provider payload (BUG-4).
- Import-time side effects: none. The sandbox, logger and BYOK factory are all
  built inside the async workflow, never at module level.
"""

from __future__ import annotations

import json
import os
import re
import resource
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

# BUG-6: mirror tools/exec_sandbox.py's proven Termux pattern — CPU/FSIZE/NPROC
# only. RLIMIT_AS is deliberately absent: Android's bionic libc aborts Python
# (SIGABRT) when the address-space cap trips during interpreter start-up.
MAX_CODE_BYTES = 256 * 1024
MAX_OUT_BYTES = 64 * 1024
MAX_TIMEOUT = 20
MAX_PROCS = 64
MAX_FSIZE = 5 * 1024 * 1024

STALL_THRESHOLD = 3
DEFAULT_MAX_ITERATIONS = 5

# JSONL observability log (one record per iteration). Override with
# NEXUS_HYPER_LOG so tests / spare runs never touch the service log.
LOG_PATH = Path(
    os.environ.get(
        "NEXUS_HYPER_LOG",
        str(Path(__file__).resolve().parent / "data" / "hyper_agent.jsonl"),
    )
)


def _log_path() -> Path:
    """Resolve the JSONL path at call time (never at import).

    The env var wins over the module-level constant so per-run overrides
    (tests, spare runs) always take effect.
    """
    env = os.environ.get("NEXUS_HYPER_LOG")
    if env:
        return Path(env)
    return LOG_PATH


def _append_log(record: Dict[str, Any]) -> None:
    """Append one JSONL record. Best-effort: a broken log must not kill a run."""
    try:
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def prune_history_fast(history: List[Dict[str, Any]], keep: int = 20) -> List[Dict[str, Any]]:
    """Return the last ``keep`` entries (BUG-1: caller REPLACES, never appends).

    WHY replace-not-append: the original bug appended the trimmed slice back
    onto the full list, so every prune grew the history instead of shrinking it.
    The function is pure — it returns a new list and leaves the input alone.
    """
    if keep <= 0:
        return []
    return list(history[-keep:])


def detect_stall(history: List[Dict[str, Any]], threshold: int = STALL_THRESHOLD) -> bool:
    """True when the last ``threshold`` actions are identical and non-terminal (BUG-3).

    Terminal actions (``DONE``/``ERROR``) never count toward a stall — a run
    that already finished cleanly is not "stalled".
    """
    if threshold <= 0 or len(history) < threshold:
        return False
    recent = history[-threshold:]
    actions = [str(entry.get("action", "")) for entry in recent]
    if any(a in {"DONE", "ERROR"} for a in actions):
        return False
    return len(set(actions)) == 1


def _fold_system_into_prompt(system_prompt: str, user_prompt: str) -> str:
    """Ollama ignores ``system_prompt``; fold it in so local runs still see it."""
    if not system_prompt:
        return user_prompt
    return f"{system_prompt}\n\n{user_prompt}"


def _make_limits() -> Callable[[], None]:
    """Build a Termux-safe ``preexec_fn`` (BUG-6).

    Mirrors ``tools/exec_sandbox.py::_make_limits``: try/except each setrlimit
    so a stricter parent cap never crashes the child; no RLIMIT_AS on Termux.
    """

    def _setlim(res: int, soft: int, hard: Optional[int] = None) -> None:
        try:
            resource.setrlimit(res, (soft, hard if hard is not None else soft))
        except (OSError, ValueError):
            pass

    def _apply() -> None:
        _setlim(resource.RLIMIT_CPU, MAX_TIMEOUT)
        _setlim(resource.RLIMIT_FSIZE, MAX_FSIZE)
        try:
            # Only cap NPROC when the parent already has a cap to lower to.
            soft, _hard = resource.getrlimit(resource.RLIMIT_NPROC)
            if soft != resource.RLIM_INFINITY:
                _setlim(resource.RLIMIT_NPROC, min(soft, MAX_PROCS))
            else:
                _setlim(resource.RLIMIT_NPROC, MAX_PROCS)
        except (OSError, ValueError):
            pass

    return _apply


def _read_cap(path: Path, cap: int = MAX_OUT_BYTES) -> str:
    """Read up to ``cap`` bytes from a file (stdout/stderr capture)."""
    try:
        data = path.read_bytes()[:cap]
        return data.decode("utf-8", errors="replace")
    except OSError:
        return ""


def run_code_sync(code: str, timeout: int = MAX_TIMEOUT) -> Dict[str, Any]:
    """Execute a Python snippet in a sandboxed subprocess (BUG-6 + BUG-7).

    BUG-7: uses ``sys.executable`` (the *current* interpreter) so the child
    matches the running Python — a bare ``python3`` can resolve to a different
    version/venv and silently break imports.
    """
    if not code or len(code.encode("utf-8", errors="replace")) > MAX_CODE_BYTES:
        return {"ok": False, "exit_code": -1, "stdout": "", "stderr": "code too large or empty"}

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        main_py = tmp_path / "main.py"
        main_py.write_text(code, encoding="utf-8")
        out_path = tmp_path / "out.txt"
        err_path = tmp_path / "err.txt"

        # BUG-7: sys.executable, not bare "python3".
        cmd = [sys.executable or "python3", str(main_py)]
        env = dict(os.environ)
        env["HOME"] = tmp
        env["TMPDIR"] = tmp
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        start = time.monotonic()
        try:
            with out_path.open("wb") as out_fh, err_path.open("wb") as err_fh:
                proc = subprocess.Popen(  # noqa: S603 — argv list, no shell
                    cmd,
                    cwd=tmp,
                    env=env,
                    stdout=out_fh,
                    stderr=err_fh,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                    preexec_fn=_make_limits() if os.name == "posix" else None,  # noqa: PLW1509
                )
                try:
                    proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    # Kill the whole session (child may have forked).
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except OSError:
                        proc.kill()
                    proc.wait()
                    return {
                        "ok": False,
                        "exit_code": -1,
                        "stdout": _read_cap(out_path),
                        "stderr": "timeout",
                        "timeout": True,
                    }
            duration_ms = int((time.monotonic() - start) * 1000)
            exit_code = proc.returncode
            return {
                "ok": exit_code == 0,
                "exit_code": exit_code,
                "stdout": _read_cap(out_path),
                "stderr": _read_cap(err_path),
                "timeout": False,
                "duration_ms": duration_ms,
            }
        except OSError as exc:  # pragma: no cover — spawn failure
            return {"ok": False, "exit_code": -1, "stdout": "", "stderr": str(exc)}


def run_tests_sync(test_dir: str, timeout: int = MAX_TIMEOUT) -> Dict[str, Any]:
    """Run pytest in ``test_dir`` with the current interpreter (BUG-7)."""
    if not test_dir or not Path(test_dir).is_dir():
        return {"ok": False, "exit_code": -1, "stdout": "", "stderr": "test_dir not found"}

    cmd = [sys.executable or "python3", "-m", "pytest", test_dir, "-q"]
    start = time.monotonic()
    try:
        proc = subprocess.run(  # noqa: S603 — argv list, no shell
            cmd,
            capture_output=True,
            timeout=timeout,
            text=True,
            start_new_session=True,
        )
        duration_ms = int((time.monotonic() - start) * 1000)
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": (proc.stdout or "")[:MAX_OUT_BYTES],
            "stderr": (proc.stderr or "")[:MAX_OUT_BYTES],
            "timeout": False,
            "duration_ms": duration_ms,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "exit_code": -1, "stdout": "", "stderr": "timeout", "timeout": True}
    except OSError as exc:  # pragma: no cover — spawn failure
        return {"ok": False, "exit_code": -1, "stdout": "", "stderr": str(exc)}


def _tokens(text: str) -> Set[str]:
    """Alphanumeric tokens of length > 2 (BUG-8 helper).

    ``re.findall`` splits punctuation too, so ``print('x')`` yields the
    token ``print`` — the tests require substring matching on both sides
    (``fib`` inside ``fibonacci``), which plain ``split()`` cannot do.
    """
    return {tok for tok in re.findall(r"[a-z0-9]+", text.lower()) if len(tok) > 2}


def verify_goal(goal: str, history: List[Dict[str, Any]]) -> bool:
    """Gate a DONE action against the actual goal (BUG-8).

    Deterministic heuristic (no LLM): tokenise the goal with the alphanumeric
    splitter and accept DONE when ANY goal token matches ANY history token by
    bidirectional substring (``fib`` ⊂ ``fibonacci``, ``print`` ⊂ ``print('x')``).
    A false VERIFY_FAIL is safer than a silent false DONE.
    """
    if not goal.strip():
        return False
    goal_tokens = _tokens(goal)
    for entry in history:
        blob = f"{entry.get('content', '')} {entry.get('result', '')}"
        blob_tokens = _tokens(blob)
        for g in goal_tokens:
            for b in blob_tokens:
                if g == b or g in b or b in g:
                    return True
    return False


def _parse_action(raw: str) -> Dict[str, Any]:
    """Parse the model's JSON action. Returns ``{"action": "ERROR", ...}`` on failure."""
    text = raw.strip()
    if not text:
        return {"action": "ERROR", "content": "empty response"}
    # Tolerate a fenced code block or leading prose.
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            candidate = part.strip()
            if candidate.startswith("json"):
                candidate = candidate[4:].strip()
            if candidate.startswith("{") and candidate.endswith("}"):
                text = candidate
                break
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"action": "ERROR", "content": f"unparseable: {text[:120]}"}
    if not isinstance(data, dict):
        return {"action": "ERROR", "content": "not a JSON object"}
    action = str(data.get("action", "")).upper()
    if not action:
        return {"action": "ERROR", "content": "missing action field"}
    data["action"] = action
    data.setdefault("content", "")
    return data


async def autonomous_workflow_hyper(
    goal: str,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    resume: Optional[Dict[str, Any]] = None,
    user_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run the autonomous loop until DONE / stall / verify_fail / iterations out.

    This is the exact call ``hyper_app/routers/agent.py`` makes (keyword args,
    ``user_config`` defaults to ``{"provider": "ollama"}``).

    Returns a state dict with at least:
      ``status``: ``"done"`` | ``"stalled"`` | ``"verify_fail"`` | ``"max_iterations"``
      ``history``: the (pruned) action history
      ``goal``: the original goal
      ``iterations``: how many cycles ran
    """
    # BYOK: resolve the connector from the per-request config (may raise ValueError).
    from hyper_app.services.llm_factory import create_llm_client_from_request

    cfg = dict(user_config) if user_config else {"provider": "ollama"}
    provider = str(cfg.get("provider", "ollama")).lower()
    llm = create_llm_client_from_request(cfg)
    is_local = provider == "ollama"

    state: Dict[str, Any] = dict(resume) if resume else {}
    # Copy the history list: sharing the same list object with a caller-supplied
    # `resume` dict would let our in-place appends mutate the caller's state.
    state["goal"] = goal
    state["history"] = list(state.get("history", []))
    state["last_parse_error"] = int(state.get("last_parse_error", 0))
    state["status"] = "running"

    system_prompt = (
        "You are an autonomous coding agent. Reply with ONE JSON object only, "
        'shape: {"action": "CODE|TEST|DONE|ERROR", "content": "..."}'
    )

    iterations_run = 0
    for _cycle in range(max(int(max_iterations), 1)):
        iterations_run += 1
        last_errors = int(state.get("last_parse_error", 0))
        err_hint = (
            f"\nNOTE: your last {last_errors} response(s) failed to parse as JSON. "
            "Reply with ONLY the JSON object."
            if last_errors
            else ""
        )
        user_prompt = (
            f"Goal: {goal}\n"
            f"Previous actions: {len(state['history'])}\n"
            f"Your turn.{err_hint}"
        )
        prompt = (
            _fold_system_into_prompt(system_prompt, user_prompt)
            if is_local
            else user_prompt
        )

        t0 = time.monotonic()
        reply = await llm.generate(prompt, system_prompt=system_prompt)
        gen_ms = int((time.monotonic() - t0) * 1000)

        if not reply.get("ok"):
            entry = {"action": "ERROR", "content": str(reply.get("error", "provider error"))}
            state["history"].append(entry)
            _append_log(
                {
                    "goal": goal,
                    "cycle": iterations_run,
                    "action": "ERROR",
                    "result": entry["content"],
                    "timing_ms": gen_ms,
                    "parsed": False,
                }
            )
            state["status"] = "verify_fail"
            break

        parsed = _parse_action(str(reply.get("reply", "")))
        parsed_ok = parsed.get("action") != "ERROR"
        if not parsed_ok:
            state["last_parse_error"] = last_errors + 1  # BUG-5
        else:
            state["last_parse_error"] = 0

        action = parsed.get("action", "ERROR")
        content = str(parsed.get("content", ""))
        result_view = ""

        if action == "CODE":
            run = run_code_sync(content)
            result_view = str(run.get("stdout", ""))[:500]
            parsed["result"] = result_view
        elif action == "TEST":
            run = run_tests_sync(content)
            result_view = str(run.get("stdout", ""))[:500]
            parsed["result"] = result_view

        # BUG-4: store a small view — never the raw provider payload.
        entry = {
            "action": action,
            "content": content[:2000],
            "result": result_view[:2000],
        }
        state["history"].append(entry)

        _append_log(
            {
                "goal": goal,
                "cycle": iterations_run,
                "action": action,
                "result": result_view[:200],
                "timing_ms": gen_ms,
                "parsed": parsed_ok,
            }
        )

        # BUG-3: stall check.
        if detect_stall(state["history"]):
            state["status"] = "stalled"
            break

        # BUG-8: DONE must pass verify_goal.
        if action == "DONE":
            if verify_goal(goal, state["history"]):
                state["status"] = "done"
            else:
                state["status"] = "verify_fail"
            break

        # BUG-1: prune REPLACES the list (never appends a trimmed copy).
        state["history"] = prune_history_fast(state["history"], keep=20)
    else:
        # Loop exhausted without a terminal action.
        if state.get("status") == "running":
            state["status"] = "max_iterations"

    state["iterations"] = iterations_run
    return state
