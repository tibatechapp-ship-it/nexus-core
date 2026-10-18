"""Phase 2 Day 1 — the agent tool library (Tool Use محور 3).

Five tools are planned across Day 1–2.  Day 1 ships the three that need no
cross-module state:

* :func:`search_web` — bounded web search (injectable fetcher → hermetic).
* :func:`read_file`      — read a text file confined to an allowed root.
* :func:`get_current_time` — injectable clock, ISO-8601 + unix.

Day 2 will add :func:`query_memory` (reads :class:`~src.learning.interactions.
InteractionStore`) and :func:`execute_code` (delegates to ``exec_sandbox``).

Security + transparency (the two additions that sit on top of the tools):

* :data:`TOOLS_CONFIG` / :func:`load_tools_config` / :func:`save_tools_config`
  — a JSON file that turns each tool on/off and caps its arguments.
* :func:`safe_execute` — the ONLY entry point an agent should call; it refuses
  a tool that is unknown or disabled in the config and never raises, returning
  a :class:`ToolResult` instead.
* Every :class:`ToolResult` carries an ``explain`` line (the "Explain" feature)
  such as ``[استخدمت search_web للبحث عن "q"]`` so the UI can show which tool
  ran and why.

The whole module is stdlib-only and free of network/clock/FS side effects at
import time, so it stays inside the phone-safe framework gate.
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
DEFAULT_CONFIG_PATH = Path(
    os.environ.get("NEXUS_TOOLS_CONFIG", "tools_config.json")
)


class ToolsConfigError(RuntimeError):
    """The config file is unreadable / not a JSON object."""


# ── config ────────────────────────────────────────────────────────────────
def default_config() -> dict[str, Any]:
    """The baseline config: every Day-1 tool enabled, Day-2 tools stubbed."""
    return {
        "version": 1,
        "tools": {
            "search_web": {"enabled": True, "max_results": SEARCH_DEFAULT_MAX},
            "read_file": {"enabled": True, "allowed_roots": ["."]},
            "get_current_time": {"enabled": True},
            # Day 2 — present so the config is the single source of truth for
            # what exists; safe_execute refuses them until they are built.
            "query_memory": {"enabled": False},
            "execute_code": {"enabled": False, "timeout": 10},
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
    """Day 2 — recall past interactions by ``keyword`` (via Phase-1 store).

    Not yet wired into :func:`safe_execute`; it is built now so Day 2 only has
    to flip the config flag.  ``store`` is injectable for hermetic tests.
    """
    if store is None:
        from src.learning.interactions import get_interaction_store

        store = get_interaction_store()
    rows = store.similar(keyword, k=max(1, min(int(limit), 20)))
    return [dict(r) for r in rows]


def execute_code(language: str, code: str,
                 *, runner: Callable[..., dict] | None = None
                 ) -> dict[str, Any]:
    """Day 2 — run ``code`` in the sandbox.  Stub until then.

    Raises a clear ``NotImplementedError`` so ``safe_execute`` returns an
    honest ``ok=False`` instead of a confusing ImportError.  Kept out of the
    enabled set until Day 2 hardens the runner (memory/timeout caps live in
    ``exec_sandbox``).
    """
    if runner is None:
        raise NotImplementedError("execute_code تُجهَّز في اليوم 2")
    return dict(runner(language, code))


# ── the registry + safe_execute ───────────────────────────────────────────
# name → (callable, explain-detail extractor).  Day-2 tools are present but
# disabled in the config, so safe_execute refuses them until they are ready.
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
    # Day-1 tools read their caps straight from the config settings.
    if tool_name == "search_web" and "max_results" not in kwargs:
        kwargs["max_results"] = int(settings.get("max_results", SEARCH_DEFAULT_MAX))
    elif tool_name == "read_file" and "allowed_roots" not in kwargs:
        roots = settings.get("allowed_roots") or ["."]
        kwargs["allowed_roots"] = list(roots)
    try:
        value = fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - the gate must never raise
        return ToolResult(ok=False, tool=tool_name, error=str(exc), explain=explain)
    return ToolResult(ok=True, tool=tool_name, value=value, explain=explain)
