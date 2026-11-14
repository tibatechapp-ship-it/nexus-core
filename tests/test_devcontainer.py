"""Devcontainer contract (M3.4): one-click install + dashboard + browser open.

الوعد: مستعرض نظيف خلال خمس دقائق — لذا كل بند هنا عقد ملزم لا نصيحة.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _config() -> dict:
    path = ROOT / ".devcontainer" / "devcontainer.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_config_parses_with_required_keys() -> None:
    config = _config()
    assert config["name"] == "nexus-core"
    assert config["image"].startswith("mcr.microsoft.com/devcontainers/python")
    assert config.get("postCreateCommand")
    assert config.get("postStartCommand")


def test_dashboard_port_forwarded_with_open_browser() -> None:
    config = _config()
    assert 8000 in config["forwardPorts"]
    attrs = config["portsAttributes"]["8000"]
    assert attrs["onAutoForward"] == "openBrowser"
    assert attrs.get("label")


def test_post_start_boots_the_dashboard() -> None:
    cmd = _config()["postStartCommand"]
    assert "uvicorn" in cmd
    assert "main:app" in cmd                      # الواجهة الموحدة (v1.61.0)
    assert "NEXUS_ALLOW_OPEN=1" in cmd            # حارس الدخول يتطلب تصريحاً صريحاً للتجربة المحلية
    assert "--port" in cmd and "8000" in cmd


def test_post_create_installs_package_and_tooling() -> None:
    cmd = _config()["postCreateCommand"]
    assert "pip install -e ." in cmd
    assert "pytest" in cmd and "ruff" in cmd and "mypy" in cmd


def test_doc_promises_five_minutes_and_port() -> None:
    doc = (ROOT / "docs" / "devcontainer.md").read_text(encoding="utf-8")
    assert "خمس دقائق" in doc
    assert "8000" in doc
    assert "python -m src.evalsuite" in doc
