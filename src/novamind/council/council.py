"""The Living Council (المجلس الحيّ) — v2.0.

A small group of specialised agents debates a topic over several rounds with
LIVE, visible streaming. After each round the council scores its own agreement
(consensus) and can stop early when the members already concur. A "chief"
member then synthesises a final verdict, and each member's influence is measured
against that verdict (standing rises / falls) — the raw signal the Genome
(v2.2) aggregates across sessions.

Design goals
- **Works offline**: with no live LLM provider the council falls back to a
  deterministic local "simulation" so tests and the phone gate never depend on
  the network. The first failed provider call flips the run into offline mode so
  a dead-key deployment stays fast (no 16 slow timeouts).
- **Pure-Python core**: consensus / influence / position parsing are plain
  functions that can be unit-tested without any backend.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Iterator, List, Optional

__all__ = ["CouncilMember", "COUNCIL_MEMBERS", "Council", "jaccard", "consensus"]


# ── tunables ─────────────────────────────────────────────────────────────────
CONSENSUS_SIM = 0.45        # two positions count as "the same" at/above this
CONSENSUS_THRESHOLD = 0.8   # largest-agreement fraction that stops early
EARLY_MIN_ROUND = 2         # never stop before this round
MAX_ROUNDS = 5
MAX_MEMBERS = 7
GENERATE_TIMEOUT = 60.0     # max wait for one live provider reply
OFFLINE_CACHE = 5.0        # how long a live failure keeps the council offline


@dataclass
class CouncilMember:
    """One voice on the council."""

    id: str
    name: str
    emoji: str
    system: str
    stance_hint: str = ""


COUNCIL_MEMBERS: List[CouncilMember] = [
    CouncilMember(
        id="analyst",
        name="المُحلِّل",
        emoji="📊",
        system=(
            "أنت «المُحلِّل» في مجلس حيّ. تنظر إلى الأرقام والأدلة والمنطق. "
            "كن دقيقاً وموضوعياً، وافترض أن الآخرين مخطئون حتى يثبت العكس. "
            "أجب بلغة الموضوع، بإيجاز (2-4 أسطر)."
        ),
        stance_hint="رأي مبنيّ على الدليل",
    ),
    CouncilMember(
        id="critic",
        name="الناقد",
        emoji="🔎",
        system=(
            "أنت «الناقد» في مجلس حيّ. مهمتك كشف المخاطر والثغرات والمغالطات "
            "وأسوأ السيناريوهات. لا تجامل أحداً. "
            "أجب بلغة الموضوع، بإيجاز (2-4 أسطر)."
        ),
        stance_hint="تحذير من مخاطر",
    ),
    CouncilMember(
        id="visionary",
        name="صاحب الرؤية",
        emoji="🚀",
        system=(
            "أنت «صاحب الرؤية» في مجلس حيّ. تنظر إلى المدى البعيد والفرص الطموحة "
            "وما يمكن أن يصير عليه الأمر. فكّر بجرأة. "
            "أجب بلغة الموضوع، بإيجاز (2-4 أسطر)."
        ),
        stance_hint="رؤية طموحة",
    ),
    CouncilMember(
        id="pragmatist",
        name="العملي",
        emoji="🛠",
        system=(
            "أنت «العملي» في مجلس حيّ. تفكّر بالتكلفة والوقت والجدوى والحدّ الأدنى "
            "القابل للتنفيذ. لا وقت للأحلام. "
            "أجب بلغة الموضوع، بإيجاز (2-4 أسطر)."
        ),
        stance_hint="حل عملي قابل للتنفيذ",
    ),
    CouncilMember(
        id="expert",
        name="الخبير",
        emoji="🎓",
        system=(
            "أنت «الخبير» في مجلس حيّ. تستدعي المعرفة المتخصّصة وأفضل الممارسات "
            "والدروس التاريخية في المجال. "
            "أجب بلغة الموضوع، بإيجاز (2-4 أسطر)."
        ),
        stance_hint="أفضل ممارسة معروفة",
    ),
]


# ── pure helpers (unit-testable, no backend) ─────────────────────────────────
_TOKEN_RE = re.compile(r"[\w\u0600-\u06FF]+", re.UNICODE)
_STANCE_RE = re.compile(r"(?:الموقف|الرأي|STANCE|POSITION)\s*[:：]\s*(.+)")


def _tokens(text: str) -> set:
    return set(_TOKEN_RE.findall((text or "").lower()))


def jaccard(a: str, b: str) -> float:
    """Token-set Jaccard similarity in [0, 1]."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def position(text: str) -> str:
    """Extract a member's declared stance from their message."""
    m = _STANCE_RE.search(text or "")
    if m:
        return m.group(1).strip().splitlines()[0][:200]
    flat = (text or "").strip().replace("\n", " ")
    return flat[-200:]


def consensus(texts: Iterable[str]) -> float:
    """Largest fraction of members whose positions agree (same stance group)."""
    pos = [position(t) for t in texts if (t or "").strip()]
    n = len(pos)
    if n == 0:
        return 0.0
    best = 0
    for i in range(n):
        group = sum(1 for j in range(n) if jaccard(pos[i], pos[j]) >= CONSENSUS_SIM)
        best = max(best, group)
    return best / n


def influence(members: List[CouncilMember], latest: Dict[str, str],
              verdict: str) -> Dict[str, Dict[str, Any]]:
    """Each member's alignment with the verdict + a standing delta (+1/−1)."""
    scores = {
        m.id: round(jaccard(latest.get(m.id, ""), verdict), 4) for m in members
    }
    if not scores:
        return {}
    avg = sum(scores.values()) / len(scores)
    return {
        k: {"alignment": v, "standing_delta": 1 if v >= avg else -1}
        for k, v in scores.items()
    }


# ── the council engine ───────────────────────────────────────────────────────
class Council:
    """Runs a live multi-agent debate and synthesises a verdict."""

    def __init__(self, router: Any = None, store: Any = None,
                 members: Optional[List[CouncilMember]] = None,
                 genome: Any = None) -> None:
        self.router = router
        self.store = store
        self.genome = genome
        self.members = list(members) if members else list(COUNCIL_MEMBERS)
        self._live = self._has_live_provider(router)
        self._provider_failed = False
        self._offline_until = 0.0

    # -- provider plumbing ----------------------------------------------------
    @staticmethod
    def _has_live_provider(router: Any) -> bool:
        if router is None:
            return False
        for p in getattr(router, "providers", []) or []:
            key = (getattr(p, "api_key", "") or "").strip()
            if getattr(p, "enabled", True) and key and key != "mock":
                return True
        return False

    def _is_offline(self) -> bool:
        """True while a recent live failure keeps us on the offline fallback."""
        if self._provider_failed and time.time() >= self._offline_until:
            self._provider_failed = False  # cache expired → allow live again
        return self._provider_failed

    def _go_offline(self) -> None:
        """Fall back to the local simulation for a while (self-healing)."""
        self._provider_failed = True
        self._offline_until = time.time() + OFFLINE_CACHE

    def _live_generate(self, member: CouncilMember,
                       prompt: str) -> Optional[Dict[str, Any]]:
        """Bounded live call — returns None on failure, timeout or empty reply."""
        box: Dict[str, Any] = {}

        def _call() -> None:
            try:
                box.update(self.router.generate(
                    prompt, system=member.system, role="fast", temperature=0.6,
                ))
            except Exception as e:  # pragma: no cover - defensive
                box["error"] = str(e)

        t = threading.Thread(target=_call, daemon=True)
        t.start()
        t.join(timeout=GENERATE_TIMEOUT)
        if t.is_alive():
            return None
        if box.get("ok") and (box.get("text") or "").strip():
            return {"text": box["text"].strip(),
                    "provider": box.get("provider", ""),
                    "elapsed": float(box.get("elapsed", 0.0))}
        return None

    def _generate(self, member: CouncilMember, prompt: str) -> Dict[str, Any]:
        """Return {text, provider, elapsed} — live provider or local fallback."""
        if self.router is not None and self._live and not self._is_offline():
            res = self._live_generate(member, prompt)
            if res is not None:
                return res
            self._go_offline()  # first live failure → offline (cached), no retries
        return {"text": self._fallback(member, prompt), "provider": "offline",
                "elapsed": 0.0}

    @staticmethod
    def _fallback(member: CouncilMember, prompt: str) -> str:
        """Deterministic offline stance so a debate always completes."""
        topic = ""
        m = re.search(r"الموضوع\s*[:：]\s*(.+)", prompt or "")
        if m:
            topic = m.group(1).strip().splitlines()[0][:120]
        return (
            f"[{member.emoji} {member.name}] بالنظر إلى «{topic or 'الموضوع'}» من "
            f"منظوري ({member.stance_hint}): الأمر يستحق دراسة جدّية، ولديّ تحفّظ "
            f"واضح على التعميم قبل توفّر بيانات أكثر.\n"
            f"الموقف: {member.name} — {member.stance_hint}"
        )

    # -- prompts --------------------------------------------------------------
    def _round_prompt(self, topic: str, member: CouncilMember, r: int,
                      rounds: int, latest: Dict[str, str]) -> str:
        head = "الموضوع: " + topic
        if r <= 1:
            return (
                head + "\n\nهذه الجولة الأولى: قدّم رأيك المبدئي بإيجاز (2-4 أسطر) "
                "من منظورك أنت. اختم بسطر يبدأ بـ «الموقف:» ثم موقفك في جملة قصيرة."
            )
        ctx = "\n".join(
            "- " + m.name + ": " + (latest.get(m.id, "")[:300])
            for m in self.members if m.id in latest
        )
        where = "هذه الجولة الأخيرة" if r >= rounds else f"الجولة {r}"
        return (
            head + "\n\nما قاله الأعضاء حتى الآن:\n" + ctx +
            f"\n\n{where}: علّق بإيجاز — أين تتفق وأين تختلف، وهل غيّرت موقفك؟ "
            "اختم بسطر «الموقف:» ثم موقفك النهائي في جملة."
        )

    def _chief_prompt(self, topic: str, latest: Dict[str, str]) -> str:
        ctx = "\n".join(
            "- " + m.name + ": " + (latest.get(m.id, "")[:400])
            for m in self.members if m.id in latest
        )
        return (
            "أنت رئيس المجلس الحيّ. اجتمع الأعضاء على الموضوع التالي وناقشوه.\n"
            "الموضوع: " + topic + "\n\nآراء الأعضاء:\n" + ctx +
            "\n\nاكتب الحكم النهائي بإيجاز (3-5 أسطر): الخلاصة والقرار، بلغة "
            "الموضوع. لا تكرّر أسماء الأعضاء."
        )

    # -- verdict --------------------------------------------------------------
    def _verdict(self, topic: str, latest: Dict[str, str]) -> Dict[str, Any]:
        if self.router is not None and self._live and not self._provider_failed:
            chief = CouncilMember(id="chief", name="رئيس المجلس", emoji="⚖️",
                                  system="أنت رئيس مجلس حكيم وموجز.")
            res = self._generate(chief, self._chief_prompt(topic, latest))
            if res["provider"] != "offline":
                return {"text": res["text"], "provider": res["provider"],
                        "offline": False}
        # offline synthesis — pick the position most shared, list the rest
        pos = {m.id: position(latest.get(m.id, "")) for m in self.members
               if latest.get(m.id)}
        best_id, best_score = None, -1.0
        for mid, p in pos.items():
            score = sum(jaccard(p, q) for q in pos.values())
            if score > best_score:
                best_id, best_score = mid, score
        lead = next((m for m in self.members if m.id == best_id), None)
        lines = ["حكم المجلس (وضع محلي — لا مزوّد متصل):", "الموضوع: " + topic, ""]
        lines.append("أبرز المواقف:")
        for m in self.members:
            if m.id in pos:
                lines.append(f"- {m.emoji} {m.name}: {pos[m.id][:160]}")
        if lead is not None:
            lines.append("")
            lines.append("القرار: الأقرب إلى إجماع المجلس هو موقف "
                         f"{lead.name} — {pos.get(lead.id, '')[:160]}")
        return {"text": "\n".join(lines), "provider": "offline", "offline": True}

    # -- the debate -----------------------------------------------------------
    def debate_stream(self, topic: str, rounds: int = 3,
                      members: Optional[List[CouncilMember]] = None
                      ) -> Iterator[Dict[str, Any]]:
        """Yield debate events; the last event (type='done') carries the result."""
        topic = (topic or "").strip() or "موضوع غير محدّد"
        try:
            rounds = int(rounds) if rounds is not None else 3
        except (TypeError, ValueError):
            rounds = 3
        rounds = max(1, min(rounds, MAX_ROUNDS))
        active = list(members)[:MAX_MEMBERS] if members else self.members[:MAX_MEMBERS]

        session: Optional[Dict[str, Any]] = None
        if self.store is not None:
            session = self.store.create_council_session(
                topic, rounds=rounds,
                meta={"members": [{"id": m.id, "name": m.name, "emoji": m.emoji}
                                  for m in active]},
            )
        sid = (session or {}).get("id", "")

        yield {"type": "session", "session_id": sid, "topic": topic,
               "rounds": rounds,
               "members": [{"id": m.id, "name": m.name, "emoji": m.emoji}
                           for m in active]}

        latest: Dict[str, str] = {}
        elapsed_map: Dict[str, float] = {}
        rounds_data: List[Dict[str, Any]] = []
        score = 0.0
        for r in range(1, rounds + 1):
            yield {"type": "round", "round": r, "total": rounds}
            msgs: List[Dict[str, Any]] = []
            for m in active:
                yield {"type": "member_start", "agent": m.id,
                       "name": m.name, "emoji": m.emoji, "round": r}
                out = self._generate(m, self._round_prompt(topic, m, r, rounds, latest))
                latest[m.id] = out["text"]
                elapsed_map[m.id] = float(out.get("elapsed", 0.0))
                if self.store is not None and sid:
                    self.store.add_council_message(
                        sid, r, m.id, out["text"], role="opinion",
                        meta={"provider": out["provider"], "elapsed": out["elapsed"]},
                    )
                ev = {"type": "member_message", "agent": m.id, "name": m.name,
                      "emoji": m.emoji, "round": r, "content": out["text"],
                      "provider": out["provider"], "elapsed": out["elapsed"]}
                yield ev
                msgs.append(ev)
            score = consensus([latest[m.id] for m in active])
            early = score >= CONSENSUS_THRESHOLD and r >= EARLY_MIN_ROUND
            yield {"type": "consensus", "round": r, "score": round(score, 3),
                   "early_stop": early}
            rounds_data.append({"round": r, "consensus": round(score, 3),
                                "messages": msgs})
            if early:
                break

        verdict = self._verdict(topic, latest)
        inf = influence(active, latest, verdict["text"])
        # Feed each member's verdict-alignment into its genome so standing
        # genuinely rises / falls across sessions (the Agent Genome loop).
        if self.genome is not None and inf:
            for m in active:
                d = inf.get(m.id, {})
                self.genome.outcome_from_influence(
                    m.id, alignment=float(d.get("alignment", 0.0)),
                    standing_delta=int(d.get("standing_delta", 0)),
                    consensus=round(score, 3),
                    latency_ms=int(elapsed_map.get(m.id, 0.0) * 1000),
                    detail={"session": sid},
                )
        if self.store is not None and sid:
            self.store.update_council_session(
                sid, status="done", verdict=verdict["text"],
                consensus=round(score, 3),
            )
        result = {
            "session_id": sid, "topic": topic, "rounds": rounds,
            "members": [{"id": m.id, "name": m.name, "emoji": m.emoji} for m in active],
            "rounds_data": rounds_data, "consensus": round(score, 3),
            "verdict": verdict["text"], "verdict_provider": verdict["provider"],
            "offline": verdict["offline"], "influence": inf,
        }
        yield {"type": "verdict", "verdict": verdict["text"],
               "consensus": round(score, 3), "influence": inf,
               "provider": verdict["provider"]}
        yield {"type": "done", "session_id": sid, "result": result}

    def debate(self, topic: str, rounds: int = 3,
               members: Optional[List[CouncilMember]] = None) -> Dict[str, Any]:
        """Run a full debate synchronously and return the final result."""
        result: Dict[str, Any] = {}
        for ev in self.debate_stream(topic, rounds=rounds, members=members):
            if ev.get("type") == "done":
                result = ev["result"]
        return result
