"""Observability tests package — disable console export during tests."""
import os
os.environ["NOVAMIND_OBS_EXPORTER"] = "none"

# Force config to reload with exporter=none
try:
    from novamind.observability.config import reset_config
    reset_config()
except Exception:
    pass
