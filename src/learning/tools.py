"""Phase 2 (Tool Use) — the agent tool library.

Five tools, all gated by one config file and one never-raising entry point:

* :func:`search_web` — bounded web search (injectable fetcher → hermetic).
* :func:`read_file`      — read a text file confined to an allowed root.
* :func:`get_current_time` — injectable clock, ISO-8601 + unix.
* :func:`query_memory`   — recall past interactions (Phase-1 :class:`InteractionStore`).
* :func:`execute_code`   — run code in the subprocess sandbox (:mod:`exec_sandbox`).

Security + transparency (the additions that sit on top of the tools):

* :func:`load_tools_config` / :func:`save_tools_config` — a JSON file that
  turns each tool on/off and caps its arguments.
* :func:`safe_execute` — the ONLY entry point an agent should call; it refuses
  a tool that is unknown or disabled in the config and never raises, returning
  a :class:`ToolResult` instead.
* Every :class:`ToolResult` carries an ``explain`` line (the "Explain" feature)
  such as ``[استخدمت search_web للبحث عن "q"]`` so the UI can show which tool
  ran and why.

Side-effect rule: nothing touches the network, the clock, the FS, or the real
sandbox at *import* time — every such dependency is an injectable keyword, so
the whole module stays inside the phone-safe framework gate at 100% coverage.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "EXEC_OUTPUT_MAX",
    "MAX_MEMORY_LIMIT",
    "MAX_READ_BYTES",
    "SEARCH_DEFAULT_MAX",
    "SEARCH_MAX_RESULTS",
    "ToolResult",
    "ToolsConfigError",
    "default_config",
    "execute_code",
    "get_current_time",
    "is_safe_path",
    "list_tools",
    "load_tools_config",
    "query_memory",
    "read_file",
    "safe_execute",
    "save_tools_config",
    "search_web",
    "tool_explain",
]

# ── hard limits (never reachable via the config) ──────────────────────────
SEARCH_MAX_RESULTS = 10          # absolute ceiling on hits returned
SEARCH_DEFAULT_MAX = 3           # the signature default the spec asks for
MAX_READ_BYTES = 256 * 1024      # 256 KB per read_file
MAX_MEMORY_LIMIT = 20            # clamp for query_memory's ``limit``
EXEC_OUTPUT_MAX = 10 * 1024      # 10 KB cap on captured stdout/stderr (Day 2)
DEFAULT_CONFIG_PATH = Path(
    os.environ.get("NEXUS_TOOLS_CONFIG", "tools_config.json")
)


class ToolsConfigError(RuntimeError):
    """The config file is unreadable / not a JSON object."""


# ── config ────────────────────────────────────────────────────────────────
def default_config() -> dict[str, Any]:
    """Baseline config: all five tools enabled; caps come from here."""
    return {
        "version": 1,
        "tools": {
            "search_web": {"enabled": True, "max_results": SEARCH_DEFAULT_MAX},
            "read_file": {"enabled": True, "allowed_roots": ["."]},
            "get_current_time": {"enabled": True},
            "query_memory": {"enabled": True, "limit": 5},
            "execute_code": {"enabled": True, "timeout": 10},
        },
    }


def load_tools_config(path: Path | str | None = None) -> dict[str, Any]:
    """Read the config; a missing file yields :func:`default_config`.

    A present-but-invalid file raises :class:`ToolsConfigError` (a silent
    fallback would hide a security-relevant setting from the operator).
    """
    cfg_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        return default_config()
    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ToolsConfigError(f"تعذّر قراءة إعدادات الأدوات: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("tools"), dict):
        raise ToolsConfigError("إعدادات الأدوات يجب أن تكون كائن JSON فيه 'tools'")
    return raw


def save_tools_config(config: dict[str, Any], path: Path | str | None = None
                      ) -> Path:
    """Persist ``config`` as pretty JSON; returns the path written."""
    cfg_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    cfg_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return cfg_path


# ── the Explain feature ───────────────────────────────────────────────────
def tool_explain(name: str, *, detail: str = "") -> str:
    """The human-readable "why did this tool run" line (AR, Latin-safe)."""
    if detail:
        return f'[استخدمت {name} للبحث عن "{detail}"]'
    return f"[استخدمت {name}]"


@dataclass(frozen=True)
class ToolResult:
    """Outcome of one :func:`safe_execute` call — never an exception."""

    ok: bool
    tool: str
    value: Any = None
    error: str | None = None
    explain: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:  # pragma: no cover - trivial convenience
        return self.ok


# ── path safety (mirrors council/craft._safe_path, kept local + tested) ──
def is_safe_path(path: str | os.PathLike[str], *,
                 allowed_roots: list[str] | tuple[str, ...] = (".",)
                 ) -> Path | None:
    """Resolve ``path`` and require it to live under an allowed root.

    Returns the resolved :class:`Path`, or ``None`` when the path escapes every
    root, is not an existing regular file, or is oversized.  Both traversal
    (``..``) and symlink escapes are neutralised by :meth:`Path.resolve`.
    """
    try:
        resolved = Path(path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not resolved.is_file():
        return None
    for root in allowed_roots:
        try:
            root_resolved = Path(root).expanduser().resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if resolved.is_relative_to(root_resolved):
            if resolved.stat().st_size > MAX_READ_BYTES:
                return None
            return resolved
    return None


# ── the Day-1 tools ───────────────────────────────────────────────────────
def search_web(query: str, max_results: int = SEARCH_DEFAULT_MAX,
               *, fetcher: Callable[[str], list[dict[str, str]]] | None = None
               ) -> list[dict[str, str]]:
    """Return up to ``max_results`` web hits ``{title, url, snippet}``.

    ``fetcher`` is injectable so tests stay offline; the default performs a
    bounded HTTPS GET against DuckDuckGo's HTML endpoint.  Any failure yields
    ``[]`` — a search outage must never take the agent down.
    """
    text = (query or "").strip()
    if not text:
        return []
    limit = max(1, min(int(max_results), SEARCH_MAX_RESULTS))
    if fetcher is None:
        fetcher = _ddg_fetch
    try:
        hits = fetcher(text)
    except Exception:
        return []
    if not isinstance(hits, list):
        return []
    clean: list[dict[str, str]] = []
    for hit in hits[:limit]:
        if not isinstance(hit, dict):
            continue
        url = str(hit.get("url", ""))
        if not url.startswith(("http://", "https://")):
            continue
        clean.append(
            {
                "title": str(hit.get("title", ""))[:200],
                "url": url[:500],
                "snippet": str(hit.get("snippet", ""))[:400],
            }
        )
    return clean


def _ddg_fetch(query: str) -> list[dict[str, str]]:
    """Minimal DuckDuckGo HTML scrape — no key, no dependency."""
    import urllib.parse
    import urllib.request

    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
    req = urllib.request.Request(
        url, headers={"User-Agent": "nexus-core/2.0 (+local agent)"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
        html = resp.read(200_000).decode("utf-8", "ignore")
    return _parse_ddg(html)


def _parse_ddg(html: str) -> list[dict[str, str]]:
    """Pure, testable extraction of hits from a DuckDuckGo HTML page."""
    import re

    hits: list[dict[str, str]] = []
    # Each result is an <a class="result__a" href="...">Title</a> optionally
    # followed by a <a class="result__snippet">…</a>.  Keep the parse lenient.
    for block in re.split(r'class="result__a"', html)[1:]:
        href = re.search(r'href="([^"]+)"', block)
        title = re.search(r'>([^<]+)</a>', block)
        snippet = re.search(r'result__snippet"[^>]*>([^<]+)', html)
        if not href or not title:
            continue
        link = href.group(1)
        if link.startswith("//"):
            link = "https:" + link
        hits.append(
            {
                "title": title.group(1).strip(),
                "url": link,
                "snippet": (snippet.group(1).strip() if snippet else ""),
            }
        )
    return hits


def read_file(path: str, *,
              allowed_roots: list[str] | tuple[str, ...] = (".",)
              ) -> dict[str, Any]:
    """Read a text file inside ``allowed_roots``; raises on any violation."""
    target = is_safe_path(path, allowed_roots=allowed_roots)
    if target is None:
        raise ValueError(f"مسار غير آمن أو غير موجود: {str(path)[:80]}")
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ValueError(f"تعذّرت قراءة الملف: {exc}") from exc
    return {"path": str(target), "bytes": len(text.encode("utf-8")),
            "content": text}


def get_current_time(*, clock: Callable[[], float] | None = None
                     ) -> dict[str, Any]:
    """Current time as ISO-8601 (local) + unix seconds; injectable clock."""
    now = (clock or time.time)()
    return {
        "unix": float(now),
        "iso": datetime.fromtimestamp(now).isoformat(timespec="seconds"),
    }


def query_memory(keyword: str, *, store: Any = None, limit: int = 5
                 ) -> list[dict[str, Any]]:
    """Recall past interactions by ``keyword`` (Phase-1 :class:`InteractionStore`).

    ``store`` is injectable for hermetic tests; the default is the process-wide
    singleton.  ``limit`` is clamped to ``[1, MAX_MEMORY_LIMIT]``.
    """
    if store is None:
        from src.learning.interactions import get_interaction_store

        store = get_interaction_store()
    rows = store.similar(keyword, k=max(1, min(int(limit), MAX_MEMORY_LIMIT)))
    return [dict(r) for r in rows]


def _default_exec_runner(language: str, code: str, *, timeout: int = 10
                         ) -> dict[str, Any]:
    """Run ``code`` in the real subprocess sandbox (``exec_sandbox._run``).

    Built lazily so importing this module never pulls in FastAPI/pydantic.  A
    missing/broken sandbox surfaces as ``RuntimeError`` (→ ``ok=False``).
    """
    try:
        from exec_sandbox import LANGS, ExecReq, _run  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover - depends on opt-in extra
        raise RuntimeError(f"بيئة التنفيذ غير متوفرة: {exc}") from exc
    lang = (language or "").strip().lower()
    if lang not in LANGS:
        raise ValueError(f"لغة غير مدعومة: {language}")
    req = ExecReq(language=lang, code=code, timeout=max(1, min(int(timeout), 10)))
    t0 = time.monotonic()
    result = _run(lang, LANGS[lang], req, req.timeout, t0)
    # Enforce the 10 KB output cap regardless of what the sandbox returned.
    if isinstance(result, dict):
        for key in ("stdout", "stderr"):
            if isinstance(result.get(key), str) and len(result[key]) > EXEC_OUTPUT_MAX:
                result[key] = result[key][:EXEC_OUTPUT_MAX]
        return dict(result)
    return {"result": result}


def execute_code(language: str, code: str, *, timeout: int = 10,
                 runner: Callable[[str, str], dict] | None = None
                 ) -> dict[str, Any]:
    """Run ``code`` in the subprocess sandbox under a strict 10s timeout.

    ``runner(language, code) -> dict`` is injectable for hermetic tests; the
    default delegates to the real ``exec_sandbox._run`` core (never the HTTP
    layer) and honours ``timeout``.  Output is capped at :data:`EXEC_OUTPUT_MAX`
    (10 KB).  A bad language, a timeout, or a broken sandbox all surface as an
    exception that :func:`safe_execute` converts to ``ok=False``.
    """
    if runner is not None:
        return dict(runner(language, code))
    return _default_exec_runner(language, code, timeout=timeout)


# ── the registry + safe_execute ───────────────────────────────────────────
# name → (callable, explain-detail extractor).  All five tools are enabled in
# the shipped config; safe_execute still refuses any tool it does not find.
_REGISTRY: dict[str, tuple[Callable[..., Any], Callable[..., str]]] = {
    "search_web": (
        search_web,
        lambda args, kwargs: str(
            kwargs.get("query") or (args[0] if args else "")
        )[:80],
    ),
    "read_file": (
        read_file,
        lambda args, kwargs: str(
            kwargs.get("path") or (args[0] if args else "")
        )[:80],
    ),
    "get_current_time": (
        get_current_time,
        lambda args, kwargs: "",
    ),
    "query_memory": (
        query_memory,
        lambda args, kwargs: str(
            kwargs.get("keyword") or (args[0] if args else "")
        )[:80],
    ),
    "execute_code": (
        execute_code,
        lambda args, kwargs: str(kwargs.get("language") or (args[0] if args else "")),
    ),
}


def list_tools(config: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """The tool table from ``config`` (name → settings), read-only view."""
    cfg = config if config is not None else load_tools_config()
    tools = cfg.get("tools", {})
    return {k: dict(v) for k, v in tools.items() if isinstance(v, dict)}


def safe_execute(tool_name: str, *args: Any,
                 config: dict[str, Any] | None = None, **kwargs: Any) -> ToolResult:
    """Run one tool under the config's ``enabled`` gate — never raises.

    This is the single entry point agents must use.  An unknown tool, a
    disabled tool, a bad argument, or an internal failure all come back as a
    ``ToolResult(ok=False, error=…)`` so a broken tool can never crash a run.
    """
    cfg = config if config is not None else load_tools_config()
    settings = (cfg.get("tools") or {}).get(tool_name)
    if settings is None:
        return ToolResult(
            ok=False, tool=tool_name,
            error=f"أداة غير معروفة: {tool_name}",
            explain=tool_explain(tool_name),
        )
    if not settings.get("enabled", False):
        return ToolResult(
            ok=False, tool=tool_name,
            error=f"أداة معطّلة: {tool_name}",
            explain=tool_explain(tool_name),
        )
    entry = _REGISTRY.get(tool_name)
    if entry is None:  # pragma: no cover - registry/config stay in sync
        return ToolResult(ok=False, tool=tool_name,
                          error=f"أداة غير مُجهّزة: {tool_name}")
    fn, detail_of = entry
    explain = tool_explain(tool_name, detail=detail_of(args, kwargs))
    # Each tool reads its caps straight from the config settings when the
    # caller did not pass them explicitly.
    if tool_name == "search_web" and "max_results" not in kwargs:
        kwargs["max_results"] = int(settings.get("max_results", SEARCH_DEFAULT_MAX))
    elif tool_name == "read_file" and "allowed_roots" not in kwargs:
        roots = settings.get("allowed_roots") or ["."]
        kwargs["allowed_roots"] = list(roots)
    elif tool_name == "query_memory" and "limit" not in kwargs:
        kwargs["limit"] = int(settings.get("limit", 5))
    elif tool_name == "execute_code" and "timeout" not in kwargs:
        kwargs["timeout"] = int(settings.get("timeout", 10))
    try:
        value = fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - the gate must never raise
        return ToolResult(ok=False, tool=tool_name, error=str(exc), explain=explain)
    return ToolResult(ok=True, tool=tool_name, value=value, explain=explain)
