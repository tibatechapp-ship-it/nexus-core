"""Independent, evidence-bound review for coding-agent patches.

The reviewer is a separate callable/provider from the patch author. It returns
a structured verdict; it never edits files, runs commands, or approves merges.
"""
from __future__ import annotations

import inspect
import json
from typing import Any, Callable

_DECISIONS = {"approve", "request_changes", "reject"}
_MAX_PATCH = 80_000
_MAX_EVIDENCE = 40_000
_MAX_FINDINGS = 40


class ReviewError(ValueError):
    """The independent review could not produce a valid, auditable verdict."""


def _parse_payload(reply: Any) -> dict[str, Any]:
    if isinstance(reply, dict):
        payload = reply
    else:
        text = str(reply)
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ReviewError("reviewer did not return a JSON object")
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ReviewError("reviewer returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ReviewError("review verdict must be an object")
    return payload


async def review_patch(
    patch: str,
    evidence: str,
    reviewer: Callable[[str], Any],
    *,
    author_provider_id: str,
    reviewer_provider_id: str,
) -> dict[str, Any]:
    """Request a separate review and validate its machine-readable verdict.

    Provider IDs are mandatory so callers cannot accidentally label a second
    prompt to the same model as an independent reviewer.
    """
    if not author_provider_id.strip() or not reviewer_provider_id.strip():
        raise ReviewError("author and reviewer provider IDs are required")
    if author_provider_id.strip().casefold() == reviewer_provider_id.strip().casefold():
        raise ReviewError("reviewer must use a provider/model identity distinct from author")
    if not isinstance(patch, str) or not patch.strip() or len(patch) > _MAX_PATCH:
        raise ReviewError("patch is empty or exceeds the review size limit")
    if not isinstance(evidence, str) or len(evidence) > _MAX_EVIDENCE:
        raise ReviewError("evidence exceeds the review size limit")

    prompt = (
        "Act as an independent senior code reviewer. Do not trust the author's "
        "claims. Review only the supplied patch and evidence. Do not execute code. "
        "Return ONLY JSON with keys: decision (approve|request_changes|reject), "
        "summary (string), findings (array of objects with severity "
        "(critical|high|medium|low|info), file (string), line (integer or null), "
        "issue (string), evidence (string)), tests_required (array of strings), "
        "confidence (number 0..1). An approval requires no unresolved critical "
        "or high findings. If evidence is insufficient, request_changes.\n"
        f"PATCH:\n{patch}\nEVIDENCE:\n{evidence}"
    )
    result = reviewer(prompt)
    if inspect.isawaitable(result):
        result = await result
    if isinstance(result, dict) and result.get("ok") is False:
        raise ReviewError("review provider failed: " + str(result.get("error", "unknown"))[:300])
    if isinstance(result, dict) and "reply" in result:
        result = result["reply"]
    payload = _parse_payload(result)

    decision = payload.get("decision")
    if decision not in _DECISIONS:
        raise ReviewError("review decision is missing or invalid")
    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 4000:
        raise ReviewError("review summary is missing or invalid")
    findings = payload.get("findings")
    if not isinstance(findings, list) or len(findings) > _MAX_FINDINGS:
        raise ReviewError("review findings must be a bounded array")
    normalized = []
    for item in findings:
        if not isinstance(item, dict) or item.get("severity") not in {
            "critical", "high", "medium", "low", "info"
        }:
            raise ReviewError("invalid finding or severity")
        if not all(isinstance(item.get(key), str) for key in ("file", "issue", "evidence")):
            raise ReviewError("each finding requires file, issue and evidence")
        line = item.get("line")
        if line is not None and (not isinstance(line, int) or line < 1):
            raise ReviewError("finding line must be a positive integer or null")
        normalized.append({
            "severity": item["severity"], "file": item["file"], "line": line,
            "issue": item["issue"][:2000], "evidence": item["evidence"][:2000],
        })
    tests = payload.get("tests_required", [])
    if not isinstance(tests, list) or len(tests) > 30 or any(
        not isinstance(item, str) or len(item) > 500 for item in tests
    ):
        raise ReviewError("tests_required must be a bounded string array")
    confidence = payload.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        raise ReviewError("confidence must be between 0 and 1")
    if decision == "approve" and any(
        item["severity"] in {"critical", "high"} for item in normalized
    ):
        decision = "request_changes"
    return {
        "decision": decision,
        "summary": summary.strip(),
        "findings": normalized,
        "tests_required": tests,
        "confidence": float(confidence),
        "author_provider_id": author_provider_id.strip(),
        "reviewer_provider_id": reviewer_provider_id.strip(),
        "independent": True,
    }
