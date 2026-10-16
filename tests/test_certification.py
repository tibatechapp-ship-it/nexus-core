"""Tests for src/certification/{signer,manager}.py — signed agent certificates.

The Ed25519 path is exercised through fake ``cryptography`` submodules because
the real Rust bindings cannot dlopen on this device (Termux/py3.14); CI runs the
genuine package. The SHA256 fallback and the fallback-on-ImportError branch are
covered directly.
"""

from __future__ import annotations

import base64 as _b64
import hashlib as _hashlib
import hmac as _hmac
import json
import os
import sys
import types
from pathlib import Path
from typing import Any

import pytest

import src.certification.signer as signer_mod
from src.certification.manager import Certificate, CertificationManager
from src.certification.signer import Signer


@pytest.fixture
def tmp_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the signer's key files into a temp dir (never touch ~/.config)."""
    keys = tmp_path / "keys"
    keys.mkdir()
    monkeypatch.setattr(signer_mod, "KEYS_DIR", keys)
    monkeypatch.setattr(signer_mod, "PRIVATE_KEY_FILE", keys / "signing.key")
    monkeypatch.setattr(signer_mod, "PUBLIC_KEY_FILE", keys / "signing.pub")
    return keys


class _Pub:
    def __init__(self, secret: bytes) -> None:
        self._secret = secret

    def public_bytes(self, encoding: Any = None, format: Any = None) -> bytes:
        return _hashlib.sha256(self._secret).digest()

    def verify(self, sig: bytes, payload: bytes) -> None:
        if sig != _hmac.new(self._secret, payload, _hashlib.sha256).digest():
            raise ValueError("invalid signature")


class _Ed25519PrivateKey:
    def __init__(self, raw: bytes) -> None:
        self._raw = raw

    @classmethod
    def generate(cls) -> "_Ed25519PrivateKey":
        return cls(os.urandom(32))

    def private_bytes(self, encoding: Any = None, format: Any = None,
                      encryption_algorithm: Any = None) -> bytes:
        return b"FAKE:" + _b64.b64encode(self._raw)

    def public_key(self) -> _Pub:
        return _Pub(self._raw)

    def sign(self, payload: bytes) -> bytes:
        return _hmac.new(self._raw, payload, _hashlib.sha256).digest()


@pytest.fixture
def fake_crypto(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install minimal cryptography submodules so the Ed25519 branch runs."""

    def load_pem_private_key(data: bytes, password: Any = None) -> _Ed25519PrivateKey:
        return _Ed25519PrivateKey(_b64.b64decode(data.split(b":", 1)[1]))

    ser = types.ModuleType("cryptography.hazmat.primitives.serialization")
    ser.Encoding = type("Encoding", (), {"PEM": "PEM", "Raw": "Raw"})
    ser.PrivateFormat = type("PrivateFormat", (), {"PKCS8": "PKCS8"})
    ser.PublicFormat = type("PublicFormat", (), {"SubjectPublicKeyInfo": "SPKI", "Raw": "Raw"})
    ser.NoEncryption = type("NoEncryption", (), {})
    ser.load_pem_private_key = load_pem_private_key

    ed = types.ModuleType("cryptography.hazmat.primitives.asymmetric.ed25519")
    ed.Ed25519PrivateKey = _Ed25519PrivateKey

    asym = types.ModuleType("cryptography.hazmat.primitives.asymmetric")
    asym.ed25519 = ed
    prim = types.ModuleType("cryptography.hazmat.primitives")
    prim.serialization = ser
    prim.asymmetric = asym
    haz = types.ModuleType("cryptography.hazmat")
    haz.primitives = prim
    root = types.ModuleType("cryptography")
    root.hazmat = haz

    for name, mod in {
        "cryptography": root,
        "cryptography.hazmat": haz,
        "cryptography.hazmat.primitives": prim,
        "cryptography.hazmat.primitives.serialization": ser,
        "cryptography.hazmat.primitives.asymmetric": asym,
        "cryptography.hazmat.primitives.asymmetric.ed25519": ed,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)


# ───────────────────────────── Signer ─────────────────────────────

def test_signer_ed25519_roundtrip(fake_crypto: None, tmp_keys: Path) -> None:
    s = Signer()
    assert s.use_ed25519 is True
    sig = s.sign({"agent": "analyst"})
    assert isinstance(sig, str) and sig
    assert s.verify({"agent": "analyst"}, sig) is True
    assert s.verify({"agent": "tampered"}, sig) is False
    assert s.public_key_b64()


def test_signer_ed25519_persists_and_reloads_key(fake_crypto: None, tmp_keys: Path) -> None:
    Signer().sign({"a": 1})
    assert (tmp_keys / "signing.key").exists() and (tmp_keys / "signing.pub").exists()
    reloaded = Signer()  # exercises the load-existing-key branch
    sig = reloaded.sign({"a": 1})
    assert reloaded.verify({"a": 1}, sig) is True


def test_signer_falls_back_on_import_error(tmp_keys: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(self: Signer) -> None:
        raise ImportError("no cryptography")

    monkeypatch.setattr(Signer, "_init_ed25519", boom)
    assert Signer().use_ed25519 is False


def test_signer_sha256_path(tmp_keys: Path) -> None:
    s = Signer(use_ed25519=False)
    assert s.use_ed25519 is False
    sig = s.sign({"x": 2})
    assert s.verify({"x": 2}, sig) is True
    assert s.verify({"x": 3}, sig) is False
    assert s.public_key_b64()


def test_signer_sha256_reloads_existing_key(tmp_keys: Path) -> None:
    Signer(use_ed25519=False).sign({"a": 1})
    reloaded = Signer(use_ed25519=False)
    sig = reloaded.sign({"a": 1})
    assert reloaded.verify({"a": 1}, sig) is True


def test_sign_verify_rejects_garbage_signature(tmp_keys: Path) -> None:
    s = Signer(use_ed25519=False)
    assert s.verify({"a": 1}, "!!!not-base64!!!") is False


# ─────────────────────── CertificationManager ───────────────────────

@pytest.fixture
def mgr(tmp_keys: Path, tmp_path: Path) -> CertificationManager:
    return CertificationManager(base_dir=tmp_path / "certs", version="9.9.9")


def test_issue_writes_signed_certificate(mgr: CertificationManager) -> None:
    cert = mgr.issue("analyst", category="core", tests={"unit": 5}, metrics={"score": 1})
    assert cert.agent == "analyst"
    assert cert.version == "9.9.9"
    assert cert.signature and cert.public_key
    assert (mgr.base_dir / "analyst.cert.json").exists()


def test_load_and_verify_valid(mgr: CertificationManager) -> None:
    mgr.issue("coder")
    assert isinstance(mgr.load("coder"), Certificate)
    result = mgr.verify("coder")
    assert result["valid"] is True
    assert result["agent"] == "coder"
    assert result["signature_alg"] in {"Ed25519", "SHA256"}


def test_verify_not_found(mgr: CertificationManager) -> None:
    assert mgr.verify("ghost") == {"agent": "ghost", "valid": False, "reason": "not_found"}


def test_load_corrupt_returns_none(mgr: CertificationManager) -> None:
    (mgr.base_dir / "broken.cert.json").write_text("{bad", encoding="utf-8")
    assert mgr.load("broken") is None
    assert mgr.list_all() == []  # corrupt entry skipped


def test_verify_tampered_signature_invalid(mgr: CertificationManager) -> None:
    mgr.issue("reviewer")
    path = mgr.base_dir / "reviewer.cert.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["agent"] = "someone-else"  # mutate the signed payload
    path.write_text(json.dumps(data), encoding="utf-8")
    assert mgr.verify("reviewer")["valid"] is False


def test_summary_aggregates(mgr: CertificationManager) -> None:
    mgr.issue("a", category="core")
    mgr.issue("b", category="planning")
    mgr.issue("c", category="core")
    summary = mgr.summary()
    assert summary["total"] == 3
    assert summary["by_category"] == {"core": 2, "planning": 1}
    assert summary["by_version"] == {"9.9.9": 3}
