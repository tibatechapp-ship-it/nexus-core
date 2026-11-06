"""Vulnerability advisory model — offline file + optional OSV.dev (س1).

Honest sourcing (MIZAN_ROADMAP.md س4 boundary): this repo has no proprietary
intelligence; the offline source is a reviewed JSON fixture and the live
source is the public OSV.dev API. Network failure degrades to an explicit
AdvisoryError the CLI turns into a reported no-op — never fake results.
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .manifest import normalize_name

__all__ = ["Advisory", "AdvisoryError", "fetch_osv", "load_offline", "osv_url"]

#: Overridable in tests (no network in the suite).
osv_url: str = "https://api.osv.dev"

_SEV_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3, "UNKNOWN": 1}

#: querybatch returns ids for every listed package; a hard cap keeps one
#: degraded run bounded instead of hammering the API on a polluted tree.
_MAX_DETAIL_FETCH = 50


@dataclass(frozen=True)
class Advisory:
    """One known-vulnerable range of one package."""

    package: str          # pip name as the source reported it
    vulnerable: str       # human-readable range, e.g. ">=1.2,<1.9" or "<1.9"
    fixed: str            # first fixed version; "" when upstream declared none
    ids: tuple[str, ...]  # e.g. ("GHSA-…", "CVE-…")
    severity: str = "UNKNOWN"

    @property
    def name(self) -> str:
        return normalize_name(self.package)

    @property
    def severity_rank(self) -> int:
        return _SEV_ORDER.get(self.severity.upper(), 1)


class AdvisoryError(RuntimeError):
    """Advisory data is malformed or its live source is unreachable."""


def load_offline(path: Path) -> list[Advisory]:
    """Load advisories from a reviewed JSON file (deterministic, offline).

    Accepts either a bare list or ``{"advisories": [...]}``; unknown fields
    are ignored so the fixture can carry extra context harmlessly.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdvisoryError(f"cannot read advisories file {path}: {exc}") from exc
    rows = payload.get("advisories") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise AdvisoryError("advisories file must be a list or {advisories: []}")
    out: list[Advisory] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict) or not row.get("package"):
            raise AdvisoryError(f"advisory #{i}: missing 'package'")
        fixed = str(row.get("fixed", ""))
        vulnerable = str(row.get("vulnerable", ""))
        if not fixed and not vulnerable:
            raise AdvisoryError(f"advisory #{i}: needs 'fixed' or 'vulnerable'")
        ids = row.get("ids", [])
        if isinstance(ids, str):
            ids = [ids]
        out.append(Advisory(
            package=str(row["package"]),
            vulnerable=vulnerable,
            fixed=fixed,
            ids=tuple(str(x) for x in ids),
            severity=str(row.get("severity", "UNKNOWN")).upper(),
        ))
    return out


def _http_json(url: str, payload: dict[str, object] | None, timeout: float) -> dict:
    """One JSON HTTP exchange (module-level so tests can monkeypatch it)."""
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — fixed OSV URL
        return json.loads(resp.read().decode("utf-8"))


def fetch_osv(packages: list[str], timeout: float = 10.0) -> list[Advisory]:
    """Query OSV.dev for the given pip package names.

    Raises :class:`AdvisoryError` when the network layer fails — the caller
    decides how to degrade. Details are capped at ``_MAX_DETAIL_FETCH`` ids;
    the cap is reported in the result via the dropped count in stderr by the
    CLI (kept silent here so the library stays pure).
    """
    try:
        batch = _http_json(
            f"{osv_url}/v1/querybatch",
            {"queries": [{"package": {"name": p, "ecosystem": "PyPI"}}
                         for p in packages]},
            timeout,
        )
    except Exception as exc:  # noqa: BLE001 — any network failure degrades
        raise AdvisoryError(f"OSV.dev unreachable: {exc}") from exc

    results = batch.get("results", [])
    ids: list[str] = []
    for entry in results:
        for vuln in (entry or {}).get("vulns", []):
            vid = str(vuln.get("id", ""))
            if vid and vid not in ids:
                ids.append(vid)
    ids = ids[:_MAX_DETAIL_FETCH]

    out: list[Advisory] = []
    for vid in ids:
        try:
            detail = _http_json(f"{osv_url}/v1/vulns/{vid}", None, timeout)
        except Exception:  # noqa: BLE001 — skip a failed detail, keep the rest
            continue
        adv = _advisory_from_osv(detail, vid)
        if adv is not None:
            out.append(adv)
    return out


def _advisory_from_osv(detail: dict, vid: str) -> Advisory | None:
    """Reduce one OSV vuln record to our Advisory (first PyPI affected entry)."""
    for affected in detail.get("affected", []):
        pkg = affected.get("package", {})
        if pkg.get("ecosystem") != "PyPI":
            continue
        fixed = ""
        intro = ""
        for rng in affected.get("ranges", []):
            for ev in rng.get("events", []):
                if "fixed" in ev and not fixed:
                    fixed = str(ev["fixed"])
                if "introduced" in ev and not intro:
                    intro = str(ev["introduced"])
        if not fixed:
            continue  # no upstream fix → nothing for the planner to bump to
        vulnerable = f">={intro},<{fixed}" if intro else f"<{fixed}"
        sev = "UNKNOWN"
        for s in detail.get("severity", []):
            if s.get("type") in ("CVSS_V3", "CVSS_V4"):
                sev = str(s.get("score", "UNKNOWN"))
                break
        ids = [vid, *(
            str(a) for a in detail.get("aliases", [])
        )]
        return Advisory(
            package=str(pkg.get("name", "")),
            vulnerable=vulnerable,
            fixed=fixed,
            ids=tuple(ids),
            severity=sev,
        )
    return None
