from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List
import os
from pathlib import Path

class Settings(BaseSettings):
    APP_NAME: str = "NovaMind Platform"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    
    SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
    
    DATABASE_URL: str = "sqlite+aiosqlite:///./novamind.db"
    
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:3001"
    
    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]
    
    NOVA_SCRIPT: str = f"{os.environ.get('NOVAMIND_HOME', str(Path(__file__).resolve().parent.parent))}/nova.py"
    
    # ═══ الحقول الإضافية من .env (16 حقل) ═══
    # البيئة والتشغيل
    app_env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8080
    
    # Hive Dashboard
    hive_dashboard_secret: str = ""
    hive_admin_user: str = "admin"
    hive_admin_pass: str = ""
    
    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    
    # SMTP / Reports
    report_smtp_host: str = ""
    report_smtp_port: int = 587
    report_smtp_user: str = ""
    report_smtp_pass: str = ""
    report_smtp_from: str = ""
    report_smtp_to: str = ""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",   # ← يسمح بحقول مستقبلية بدون كسر
    )


# ═══════════════════════════════════════════════════════════
# Execution & Workspace Constants
# ═══════════════════════════════════════════════════════════

# Timeout للتنفيذ (بالثواني) — 5 دقائق افتراضياً
EXECUTE_TIMEOUT: int = int(os.environ.get("EXECUTE_TIMEOUT", "300"))

# مجلد العمل الرئيسي
WORKSPACE_DIR: Path = Path(
    os.environ.get("WORKSPACE_DIR", str(Path(__file__).resolve().parent))
)

# ضمان وجود المجلد
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()

# ═══ Runtime constants (added for backward compatibility) ═══
EXECUTE_TIMEOUT = int(os.getenv("EXECUTE_TIMEOUT", "300"))
WORKSPACE_DIR = os.getenv("WORKSPACE_DIR", "/tmp/novamind_workspace")
MAX_FIX_ATTEMPTS = int(os.getenv("MAX_FIX_ATTEMPTS", "3"))
