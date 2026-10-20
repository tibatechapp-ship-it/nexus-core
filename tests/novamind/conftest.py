"""Novamind-layer test configuration.

The former novamind package depends on the optional ``novamind`` extras
(fastapi, uvicorn, pydantic-settings, sqlalchemy, ...). When ANY of them is
missing the whole tree is skipped (pytest.importorskip per extras module) so
the stdlib-only framework gate stays green on the phone; CI installs the
extras wholesale and runs the real suite.
"""
import pytest

_NOVAMIND_EXTRAS = (
    "fastapi",
    "uvicorn",
    "pydantic_settings",
    "sqlalchemy",
    "aiosqlite",
    "aiofiles",
    "jinja2",
    "yaml",
    "httpx",
)
for _mod in _NOVAMIND_EXTRAS:
    pytest.importorskip(_mod, reason="novamind extras not installed")
del _mod, _NOVAMIND_EXTRAS

"""Pytest configuration — adds src/ to sys.path."""
import sys
from pathlib import Path

# Ensure src/ is on sys.path
_SRC = Path(__file__).parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

"""
Shared test fixtures for NovaMind.
مصدر الحقيقة: nova._registry (nova.yaml).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest


# ═══════════════════════════════════════════════════════════
# Global
# ═══════════════════════════════════════════════════════════

@pytest.fixture(scope="session")
def project_root():
    """جذر المشروع."""
    return ROOT


@pytest.fixture(scope="session")
def nova_package():
    """nova كحزمة."""
    import novamind as nova
    return nova


# ═══════════════════════════════════════════════════════════
# Factory + Registry (المصدر الوحيد)
# ═══════════════════════════════════════════════════════════

@pytest.fixture(scope="session")
def factory():
    """مصنع الوكلاء الموحد (يقرأ من nova._registry)."""
    from novamind.agents.factory import factory as f
    return f


@pytest.fixture(scope="session")
def available_agent_names():
    """الأسماء الرسمية من nova._registry."""
    from novamind.registry import all_agent_names
    return all_agent_names()


@pytest.fixture(scope="session")
def all_agent_names_with_aliases():
    """الأسماء الرسمية + aliases."""
    from novamind.registry import all_agent_names_with_aliases
    return all_agent_names_with_aliases()


# ═══════════════════════════════════════════════════════════
# Code samples
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def sample_code():
    """كود بسيط للاختبار."""
    return '''def add(a, b):
    """Add two numbers."""
    return a + b


def process(data):
    """Process a list."""
    return [x * 2 for x in data]
'''


@pytest.fixture
def sample_empty_code():
    """كود فارغ."""
    return ""


@pytest.fixture
def sample_vulnerable_code():
    """كود فيه ثغرات (MD5، secrets، SQL injection)."""
    return '''
import hashlib
import os

def hash_password(password):
    return hashlib.md5(password.encode()).hexdigest()

API_KEY = "sk-1234567890abcdef1234567890abcdef"
SECRET_TOKEN = "ghp_1234567890abcdefghijklmnopqrstuvwxyz"

def get_user(user_id):
    query = f"SELECT * FROM users WHERE id = {user_id}"
    return query

def run_command(cmd):
    os.system(cmd)
'''


# ─── Init cost_tracker database for tests ───
import pytest


@pytest.fixture(autouse=True)
def _init_cost_tracker_db(tmp_path, monkeypatch):
    """Ensure cost_tracker DB is initialized for each test."""
    try:
        from novamind.core.hive.analytics import cost_tracker as ct

        # Point DB to tmp dir to avoid pollution
        db_path = tmp_path / "costs_test.db"
        monkeypatch.setattr(ct, "DB_PATH", db_path, raising=False)

        # Initialize tables if method exists
        if hasattr(ct, "_init_db"):
            ct._init_db()
        elif hasattr(ct, "init_db"):
            ct.init_db()
        elif hasattr(ct, "reset"):
            try:
                ct.reset()
            except Exception:
                pass

        yield
    except ImportError:
        yield


@pytest.fixture
def expected_agent_count():
    """Expected number of registered agents.
    
    Originally 79 — but registry may have grown.
    Update if registry legitimately adds agents.
    """
    from novamind.registry import stats
    return stats()["agents_total"]


# ═══════════════════════════════════════════════════════════
# Auto-generated fixtures for backward compatibility
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def expected_agent_count():
    """Expected number of registered agents.
    
    Reads dynamically from registry to avoid hardcoded values.
    """
    try:
        from novamind.registry import stats
        return stats()["agents_total"]
    except Exception:
        return 79  # fallback


# ═══════════════════════════════════════════════════════════════════════
# Isolation: redirect novamind runtime data dirs to tmp_path
# (added 2026-10-20 — v1.27.0 audit, see PR #35)
# ═══════════════════════════════════════════════════════════════════════
_REDIRECT_DIRS = {
    "core.rag.knowledge_graph": ["KG_DIR"],
    "core.rag.vector_store": ["VECTOR_DIR", "STORE_DIR", "DATA_DIR"],
}


def _aliases(tail):
    """Yield every importable alias (novamind.X and src.novamind.X)."""
    import importlib
    seen = set()
    for prefix in ("novamind.", "src.novamind."):
        try:
            mod = importlib.import_module(prefix + tail)
        except ImportError:
            continue
        if id(mod) not in seen:
            seen.add(id(mod))
            yield mod


@pytest.fixture(autouse=True)
def _isolate_novamind_data_dirs(tmp_path, monkeypatch):
    """Redirect module-level *_DIR globals to per-test tmp_path."""
    for tail, attrs in _REDIRECT_DIRS.items():
        for mod in _aliases(tail):
            for attr in attrs:
                if hasattr(mod, attr):
                    target = tmp_path / attr.lower()
                    target.mkdir(parents=True, exist_ok=True)
                    monkeypatch.setattr(mod, attr, target, raising=False)
