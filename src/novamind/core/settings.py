"""
NovaMind Settings — Professional configuration system.

Uses Pydantic Settings + platformdirs for:
- Type-safe configuration
- Automatic .env loading
- Multi-environment support (dev/staging/prod/CI)
- OS-standard paths (via platformdirs)
- Writable directory verification
"""
from pathlib import Path
from typing import Optional, Literal
import os

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

try:
    from platformdirs import user_data_dir, user_cache_dir, user_log_dir
    PLATFORMDIRS_AVAILABLE = True
except ImportError:
    PLATFORMDIRS_AVAILABLE = False


# ═══════════════════════════════════════════════════════
# Environment detection
# ═══════════════════════════════════════════════════════
def detect_environment() -> str:
    """Auto-detect environment."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return "ci"
    if os.environ.get("VERCEL"):
        return "vercel"
    if os.environ.get("RAILWAY"):
        return "railway"
    if Path("/.dockerenv").exists():
        return "docker"
    return "development"


def find_project_root() -> Path:
    """Find project root by looking for markers."""
    markers = ["pyproject.toml", "agents", "core", ".git"]
    current = Path(__file__).parent.parent.parent  # core/settings.py → root

    # Try from current file
    for _ in range(5):
        if any((current / m).exists() for m in markers):
            return current
        current = current.parent

    return Path.cwd()


def get_default_home() -> Path:
    """
    Get default home directory.
    Priority:
    1. NOVAMIND_HOME env (highest)
    2. Project root (dev — has pyproject.toml or agents/)
    3. platformdirs user_data_dir (production)
    """
    # 1. Explicit env var (from shell or .env)
    env_home = os.environ.get("NOVAMIND_HOME")
    if env_home:
        return Path(env_home).expanduser().resolve()

    # 2. Project root — most reliable for dev
    root = find_project_root()
    if (root / "pyproject.toml").exists() or (root / "agents").exists():
        return root

    # 3. platformdirs (OS standard)
    if PLATFORMDIRS_AVAILABLE:
        return Path(user_data_dir("novamind", "novamind"))

    return Path.cwd()


def safe_mkdir(path: Path) -> Path:
    """
    Create directory safely. Fallback to temp if permission denied.
    """
    try:
        path.mkdir(parents=True, exist_ok=True)
        # Test writability
        test = path / ".write_test"
        test.touch()
        test.unlink()
        return path
    except (PermissionError, OSError):
        import tempfile
        fallback = Path(tempfile.gettempdir()) / "novamind" / path.name
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


# ═══════════════════════════════════════════════════════
# Settings class
# ═══════════════════════════════════════════════════════
class NovaMindSettings(BaseSettings):
    """
    NovaMind configuration. Loaded from:
    1. Environment variables (highest priority)
    2. .env file
    3. Defaults (lowest)
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_prefix="",  # No prefix (use NOVAMIND_HOME directly)
    )

    # ═══ Environment ═══
    environment: Literal["development", "ci", "staging", "production",
                          "docker", "vercel", "railway"] = Field(
        default_factory=detect_environment
    )

    # ═══ Home Directory ═══
    novamind_home: Optional[Path] = Field(default=None)

    # ═══ Runtime Directories (relative to home) ═══
    memory_subdir: str = "memory"
    logs_subdir: str = "logs"
    workspace_subdir: str = "workspace"
    data_subdir: str = "data"

    # ═══ Feature Flags ═══
    enable_rag: bool = True
    enable_learning: bool = True
    enable_metrics: bool = True
    debug: bool = False

    # ═══ LLM Provider Keys (optional, loaded from env) ═══
    gemini_api_key: str = ""
    groq_api_key: str = ""
    openai_api_key: str = ""

    # ═══ Validators ═══
    @field_validator("novamind_home", mode="before")
    @classmethod
    def resolve_home(cls, v):
        if v is None:
            return get_default_home()
        return Path(v).expanduser().resolve()

    # ═══ Computed Properties ═══
    @property
    def memory_dir(self) -> Path:
        return safe_mkdir(self.novamind_home / self.memory_subdir)

    @property
    def logs_dir(self) -> Path:
        return safe_mkdir(self.novamind_home / self.logs_subdir)

    @property
    def workspace_dir(self) -> Path:
        return safe_mkdir(self.novamind_home / self.workspace_subdir)

    @property
    def data_dir(self) -> Path:
        return safe_mkdir(self.novamind_home / self.data_subdir)

    # ═══ Specific Subdirectories ═══
    @property
    def vector_store_dir(self) -> Path:
        return safe_mkdir(self.memory_dir / "vector_store")

    @property
    def knowledge_graph_dir(self) -> Path:
        return safe_mkdir(self.memory_dir / "knowledge_graph")

    @property
    def providers_dir(self) -> Path:
        return safe_mkdir(self.memory_dir / "providers")

    @property
    def projects_dir(self) -> Path:
        return safe_mkdir(self.memory_dir / "projects")

    @property
    def repos_dir(self) -> Path:
        return safe_mkdir(self.memory_dir / "repos")

    @property
    def learning_file(self) -> Path:
        return self.memory_dir / "learning.json"

    @property
    def users_file(self) -> Path:
        return self.memory_dir / "users.json"

    # ═══ Helper methods ═══
    def is_ci(self) -> bool:
        return self.environment == "ci"

    def is_dev(self) -> bool:
        return self.environment == "development"

    def to_dict(self) -> dict:
        """Export non-sensitive config."""
        return {
            "environment": self.environment,
            "novamind_home": str(self.novamind_home),
            "memory_dir": str(self.memory_dir),
            "logs_dir": str(self.logs_dir),
            "workspace_dir": str(self.workspace_dir),
            "enable_rag": self.enable_rag,
            "enable_learning": self.enable_learning,
            "enable_metrics": self.enable_metrics,
            "debug": self.debug,
        }


# ═══════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════
settings = NovaMindSettings()


# ═══════════════════════════════════════════════════════
# Backward compatibility (for existing code)
# ═══════════════════════════════════════════════════════
NOVAMIND_HOME = settings.novamind_home
MEMORY_DIR = settings.memory_dir
LOGS_DIR = settings.logs_dir
WORKSPACE_DIR = settings.workspace_dir
VECTOR_STORE_DIR = settings.vector_store_dir
KG_DIR = settings.knowledge_graph_dir
PROVIDERS_DIR = settings.providers_dir


# ═══════════════════════════════════════════════════════
# CLI test
# ═══════════════════════════════════════════════════════
if __name__ == "__main__":
    import json
    print(json.dumps(settings.to_dict(), indent=2, ensure_ascii=False))
