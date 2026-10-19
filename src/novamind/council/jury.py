"""Jury gate — fires ONLY on HIGH risk. Hardened against prompt injection."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import json
import re
from src.orchestrator.risk import RiskLevel


@dataclass
class JuryVerdict:
    approved: bool
    confidence: float
    blocking_issues: List[str]
    members_consulted: int
    members_approved: int
    member_verdicts: Dict[str, Dict[str, Any]]


def _sanitize_target(text: str) -> str:
    """Basic hardening: prevent boundary breakouts in the prompt."""
    t = str(text or "")[:2000]
    t = t.replace(chr(96) * 3, "---")     # ``` → ---
    t = t.replace(chr(34) * 3, chr(39) * 3)  # triple-dq -> triple-sq
    return t


def _invoke_member(member_id: str, target: str, llm: Any) -> Dict[str, Any]:
    try:
        if llm is None or not hasattr(llm, "generate"):
            return {"approved": False, "confidence": 0.0,
                    "issues": ["no_llm"], "abstain": True}
        sanitized = _sanitize_target(target)
        prompt = (
            f"You are {member_id}. Judge STRICTLY. Respond JSON only: "
            '{{"approved": true|false, "confidence": 0..1, "issues": ["..."]}}\n\n'
            f"CONTEXT START:\n{sanitized}\nCONTEXT END\n\n"
            "Evaluate if the CONTEXT is safe and correct."
        )
        raw = llm.generate(prompt, json_mode=True, temperature=0.0)
        m = re.search(r"\{.*\}", raw or "", re.S)
        if not m:
            return {"approved": False, "confidence": 0.0,
                    "issues": ["parse_error"], "abstain": True}
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return {"approved": False, "confidence": 0.0,
                    "issues": ["invalid_json"], "abstain": True}
        return {"approved": bool(data.get("approved")),
                "confidence": float(data.get("confidence", 0.0) or 0.0),
                "issues": list(data.get("issues") or [])}
    except Exception as e:
        return {"approved": False, "confidence": 0.0,
                "issues": [f"error:{str(e)[:80]}"], "abstain": True}


def judge(target, *, risk, members, llm=None):
    if risk != RiskLevel.HIGH:
        return None
    verdicts = {m: _invoke_member(m, target, llm) for m in members}
    real = [v for v in verdicts.values() if not v.get("abstain")]
    if not real:
        return JuryVerdict(approved=False, confidence=0.0,
                           blocking_issues=["all_members_abstained"],
                           members_consulted=len(members),
                           members_approved=0, member_verdicts=verdicts)
    approved_count = sum(1 for v in real if v["approved"])
    majority = approved_count * 2 > len(real)
    avg_conf = sum(v["confidence"] for v in real) / len(real)
    blocking = sorted({i for v in real if not v["approved"] for i in v["issues"]})
    return JuryVerdict(approved=majority, confidence=round(avg_conf, 3),
                       blocking_issues=blocking,
                       members_consulted=len(members),
                       members_approved=approved_count,
                       member_verdicts=verdicts)
