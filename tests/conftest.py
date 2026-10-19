"""Shared pytest fixtures for the tyb-zyv-ai test-suite.

The two assistants are single-file *scripts* whose names contain a hyphen
(``zyvo-telegram.py``), so they cannot be imported with a normal ``import``.
We load them here with :mod:`importlib` and expose them as fixtures.

Both modules are pure standard-library and, at import time, do not touch the
network or spawn processes (only ``os.makedirs`` on a temp work dir), so loading
them is safe and fast.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import types
from collections.abc import Generator
from pathlib import Path

import pytest

ROOT: Path = Path(__file__).resolve().parent.parent
_TESTS_DIR: Path = Path(__file__).resolve().parent
_ADVERSARIAL_DIR: Path = _TESTS_DIR / "adversarial"

# The adversarial suite lives in its own sub-directory and imports `report` and
# `attacks` from there, plus the shared `deep_helpers` from tests/. Put both dirs
# on sys.path up-front so those imports resolve regardless of collection order.
for _entry in (str(_ADVERSARIAL_DIR), str(_TESTS_DIR)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

# The ``tools/`` package dir holds the exec sandbox (``exec_sandbox.py``), which
# is imported by its top-level name (``exec_sandbox``).  Put ``tools/`` on
# sys.path up-front so those imports resolve regardless of collection order and
# regardless of how the process was bootstrapped.
_TOOLS_DIR: Path = ROOT / "tools"
if _TOOLS_DIR.is_dir() and str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

# The access guard (src/security/access.py) auto-enables itself when
# NEXUS_AUTH_TOKEN is present in the environment. The suite assumes it is OFF,
# so a developer's local guard config (an exported shell var, or a `.env` the
# app re-reads via load_dotenv) must not leak in — otherwise mutating requests
# inside the tests come back 401. Clear it before any test module imports.
for _guard_var in (
    "NEXUS_AUTH_TOKEN",
    "NEXUS_RATE_LIMIT",
    "NEXUS_RATE_WINDOW",
    "NEXUS_AUDIT_LOG",
):
    os.environ.pop(_guard_var, None)

# Phase-1 interaction memory (src/learning/interactions.py) resolves its DB
# from $NEXUS_INTERACTIONS_DB → $NEXUS_DB sibling → <repo>/data. Without this
# the suite would write into the repo's real data/interactions.db; give every
# run a private temp database instead (a deliberate per-test path still wins).
os.environ.setdefault(
    "NEXUS_INTERACTIONS_DB",
    str(Path(tempfile.gettempdir()) / f"nexus-test-interactions-{os.getpid()}.db"),
)

# The genome store (src/novamind/genome_store.py) resolves its file the same
# way, so point it at a private temp file too — a test that installs the genome
# layer must never rewrite the repo's real data/genome.json.
os.environ.setdefault(
    "NEXUS_GENOME_PATH",
    str(Path(tempfile.gettempdir()) / f"nexus-test-genome-{os.getpid()}.json"),
)

from report import AdversarialReport  # noqa: E402  (after sys.path is set)

#: The one adversarial verdict ledger, shared for the whole session.
REPORT = AdversarialReport()


def vec_extension_available() -> bool:
    """True when the ``vec0`` SQLite extension can actually be loaded.

    ``sqlite-vec`` ships as a *loadable extension* (``vec0.so``), not an
    importable module, so ``pytest.importorskip("sqlite_vec")`` cannot detect it.
    The only honest probe is to try ``load_extension`` once; on a host without
    the ``.so`` (e.g. CI) this is ``False`` and the RAG tests skip instead of
    failing with ``RuntimeError: sqlite-vec غير مثبت``.
    """
    import sqlite3

    conn = sqlite3.connect(":memory:")
    try:
        conn.enable_load_extension(True)
        conn.load_extension("vec0")
        return True
    except Exception:
        return False
    finally:
        conn.close()


#: Skip marker for any test that needs a working ``vec0`` store.
requires_vec = pytest.mark.skipif(
    not vec_extension_available(),
    reason="sqlite-vec extension (vec0) not installed",
)


def sandbox_available() -> bool:
    """True when the top-level ``exec_sandbox`` module can be located.

    ``tools/exec_sandbox.py`` is a local-only helper (gitignored) so it is
    absent from clean checkouts / CI.  Tests that actually run code through the
    real sandbox must be skipped there rather than fail.
    """
    try:
        return importlib.util.find_spec("exec_sandbox") is not None
    except Exception:
        return False


#: Skip marker for any test that needs the real ``exec_sandbox`` runner.
requires_sandbox = pytest.mark.skipif(
    not sandbox_available(),
    reason="exec_sandbox module (tools/exec_sandbox.py) not present",
)


def _load(name: str, filename: str) -> types.ModuleType:
    """Import a hyphenated script by path under a valid module name."""
    path = ROOT / filename
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)  # runs top-level defs only (__main__ guarded)
    return module


@pytest.fixture(scope="session")
def tg() -> types.ModuleType:
    """The loaded ``zyvo-telegram.py`` module."""
    return _load("zyvo_telegram_under_test", "zyvo-telegram.py")


@pytest.fixture(scope="session")
def voice() -> types.ModuleType:
    """The loaded ``zyvo-voice.py`` module."""
    return _load("zyvo_voice_under_test", "zyvo-voice.py")


@pytest.fixture(autouse=True)
def _reset_module_state() -> None:
    """Reset mutable module globals before each test for isolation.

    Only touches the two scripts when they are ALREADY loaded (they are loaded
    on demand by the ``tg``/``voice`` fixtures). Requesting them here would
    force-load both for every test in the suite -- wasteful, and it used to
    surface any import-time failure as an error on unrelated tests (e.g.
    ``tests/novamind``). Modules are simply absent until a test needs them.
    """
    tg = sys.modules.get("zyvo_telegram_under_test")
    if tg is not None:
        with tg.PARTS_LOCK:
            tg.PARTS.clear()
        tg.PAUSED = False
        tg.CURRENT_SID = None
        tg.RUNNING_TURN = False
        tg._PROC = None
    voice = sys.modules.get("zyvo_voice_under_test")
    if voice is not None:
        voice.ACTION = "always"
        voice._PROC = None


class FakePopen:
    """Minimal stand-in for ``subprocess.Popen`` used by the server launcher.

    ``start_new_session=True`` is used by the real code (for killpg), so we
    mimic the small surface the scripts rely on: ``pid``, ``poll``, ``terminate``.
    """

    last: "FakePopen | None" = None

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.args = args
        self.kwargs = kwargs
        self.pid = 424242
        self.returncode: int | None = None
        FakePopen.last = self

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.returncode = -15

    def wait(self, timeout: float | None = None) -> int | None:
        return self.returncode or 0


class FakeResponse:
    """Context-manager stand-in for ``urllib.request.urlopen``'s return value."""

    def __init__(self, body: bytes = b"{}", status: int = 200) -> None:
        self._body = body
        self.status = status
        self.headers: dict[str, str] = {}

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body

    def __iter__(self) -> object:
        # urlopen() on the SSE stream returns an iterable of lines.
        return iter(self._body.splitlines(keepends=True))


# ── adversarial suite: verdict ledger + report hooks ────────────────────
# Every test in a module that sets ``CATEGORY`` becomes a verdict for the
# session report: PASS → HELD, FAIL → BROKEN. The table prints at the end.
# (Markers ``adversarial``/``slow`` are registered in pyproject.toml.)


@pytest.fixture(scope="session")
def adversarial_report() -> AdversarialReport:
    """The session-wide adversarial report ledger."""
    return REPORT


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo
) -> Generator[None, object, None]:
    """Record one held/broken verdict for every adversarial test that runs."""
    outcome: object = yield
    report = getattr(outcome, "get_result")()
    if getattr(report, "when", None) != "call":
        return
    module = getattr(item, "module", None)
    category = getattr(module, "CATEGORY", None) if module is not None else None
    if category is None or getattr(report, "skipped", False):
        return
    passed = bool(getattr(report, "passed", False))
    detail = "" if passed else str(getattr(report, "longreprtext", ""))[:300]
    REPORT.record(str(category), item.name, held=passed, detail=detail)


def pytest_terminal_summary(
    terminalreporter: object, exitstatus: int, config: pytest.Config
) -> None:
    """Print the adversarial report table (only when vectors actually ran)."""
    write_line = getattr(terminalreporter, "write_line", None)
    if write_line is None or REPORT.total == 0:
        return
    write_line("")
    for line in REPORT.summary().splitlines():
        write_line(line)
    if REPORT.broken_count:
        write_line(f"  {REPORT.broken_count} vector(s) BROKEN — see ADVERSARIAL.md")
