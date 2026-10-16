"""Certificate Manager — إصدار وإدارة شهادات الوكلاء."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.certification.signer import Signer

__all__ = ["Certificate", "CertificationManager"]

CERTS_DIR = Path.home() / ".config" / "nexus" / "certificates"


@dataclass
class Certificate:
    """شهادة اعتماد وكيل."""
    agent: str
    version: str
    issued_at: str
    issuer: str = "nexus-core"
    category: str = "core"
    tests: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    signature: str = ""
    public_key: str = ""
    
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
    
    def to_signed_dict(self) -> dict[str, Any]:
        """البيانات التي تُوقّع (بدون التوقيع)."""
        return {
            "agent": self.agent,
            "version": self.version,
            "issued_at": self.issued_at,
            "issuer": self.issuer,
            "category": self.category,
            "tests": self.tests,
            "metrics": self.metrics,
        }


class CertificationManager:
    """يدير كل الشهادات."""
    
    def __init__(self, base_dir: Path = CERTS_DIR, version: str = "1.13.0") -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.version = version
        self.signer = Signer()
    
    def _path(self, agent: str) -> Path:
        return self.base_dir / f"{agent}.cert.json"
    
    def issue(
        self,
        agent: str,
        category: str = "core",
        tests: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> Certificate:
        """يُصدر شهادة موقّعة."""
        cert = Certificate(
            agent=agent,
            version=self.version,
            issued_at=datetime.now(timezone.utc).isoformat(),
            category=category,
            tests=tests or {},
            metrics=metrics or {},
        )
        
        # وقّع
        sig = self.signer.sign(cert.to_signed_dict())
        cert.signature = sig
        cert.public_key = self.signer.public_key_b64()
        
        # احفظ
        path = self._path(agent)
        path.write_text(
            json.dumps(cert.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        
        return cert
    
    def load(self, agent: str) -> Certificate | None:
        """يحمّل شهادة."""
        path = self._path(agent)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Certificate(**data)
        except Exception:
            return None
    
    def verify(self, agent: str) -> dict[str, Any]:
        """يتحقق من شهادة."""
        cert = self.load(agent)
        if cert is None:
            return {"agent": agent, "valid": False, "reason": "not_found"}
        
        # تحقق من التوقيع
        signed_data = cert.to_signed_dict()
        is_valid = self.signer.verify(signed_data, cert.signature)
        
        return {
            "agent": agent,
            "valid": is_valid,
            "issued_at": cert.issued_at,
            "version": cert.version,
            "category": cert.category,
            "signature_alg": "Ed25519" if self.signer.use_ed25519 else "SHA256",
        }
    
    def list_all(self) -> list[Certificate]:
        """يعيد كل الشهادات."""
        certs: list[Certificate] = []
        for path in sorted(self.base_dir.glob("*.cert.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                certs.append(Certificate(**data))
            except Exception:
                continue
        return certs
    
    def summary(self) -> dict[str, Any]:
        """ملخص الشهادات."""
        certs = self.list_all()
        by_category: dict[str, int] = {}
        by_version: dict[str, int] = {}
        
        for cert in certs:
            by_category[cert.category] = by_category.get(cert.category, 0) + 1
            by_version[cert.version] = by_version.get(cert.version, 0) + 1
        
        return {
            "total": len(certs),
            "by_category": by_category,
            "by_version": by_version,
            "issuer": "nexus-core",
            "signature_alg": "Ed25519" if self.signer.use_ed25519 else "SHA256",
        }
