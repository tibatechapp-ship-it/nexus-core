# MORNING REPORT — nexus-core v2.0 (overnight run, 2026-10-12 → 13)

**Branch:** `feature/landing-page` · **Latest commits:**
`2ef36f8` PWA · `400a56c` Agent Genome · `f6ba51e` The Living Council ·
`2dee610…9740512` v1.5 (SQLite + Time Machine + UI)

Everything the VISION_2026.md roadmap promised for v2.0 is **built, verified
and pushed**. Total for the night: **2916 insertions across 30 files**.

---

## 1) What is new — v2.0

### ⚖️ The Living Council (المجلس الحيّ)
- 5 specialised members debate live with **streaming**: analyst, critic,
  visionary, pragmatist, expert — 1–5 rounds, per-round consensus
  (token-Jaccard), early stop at ≥ 0.8, chief verdict.
- **Idea → reality**: only the 5 core members were in the VISION; built with
  room for up to 7 (`MAX_MEMBERS`).
- Pure helper math (jaccard/position/consensus/influence) is unit-tested and
  stdlib-only — **the council works fully OFFLINE** (deterministic local
  simulation), so the phone and CI need no network or keys.
- SSE endpoints + full UI (topbar ⚖️ → debate modal with live member chips,
  bubbles, consensus bars, verdict card, history).

### 🧬 Agent Genome (جينوم الوكلاء)
- Agents now **evolve**: after every debate, each member's standing
  (success 0.6 / consensus 0.3 / speed 0.1 → 0–1) rises or falls by how well
  it agreed with the verdict; classified `promoted / active / probation`.
- Full lifecycle API: seed, record, reset, rank, detail, export/import +
  editable persona (the "re-train" button).
- Genome panel in the UI (topbar 🧬): ranked rows with 🥇🥈🥉, standing bars,
  status pills, per-agent evolution timeline.
- Live-verified: offline debate → 4 members promoted (0.76), critic on
  probation (0.16) — the loop demonstrably works.

### 📱 PWA + Offline (installable app)
- Installable web app: manifest, 3 icons (192/512/maskable, drawn by a
  stdlib PNG writer), "تثبيت التطبيق" (install) button.
- Service worker precaches the shell; **verified: full UI still loads after
  going fully offline** (headless Chromium test).
- Offline message queue: send while offline → message pinned `⏳ n` in the
  composer → auto-replayed the moment connection returns.
- Server serves everything: `/manifest.json`, `/sw.js`, `/offline.html`,
  `/icon-{192|512|maskable-512}.png`.

---

## 2) Verification (all green)

| Gate | Result |
|---|---|
| `pytest --cov` | **1312 passed** (1 skip) @ **98.78%** (floor 95%) |
| `ruff check .` | clean |
| `mypy` (framework) | clean, 95 files |
| `check_annotations.py` | 95/95 typed |
| Live server smoke (TestClient) | health/council/genome/PWA all 200 |
| Headless Chromium (CDP) | council stream, genome UI, **offline reload** ✅ |

**One fix along the way** — `tests/novamind/conftest.py` only gated on
`fastapi`, so a phone with fastapi but without the other novamind deps broke
the whole pytest collection. It now importorskips the full extras set; CI
(which installs everything) is unaffected.

---

## 3) How to run

```bash
PYTHONPATH=src/novamind:src:. python unified_agent.py   # → http://127.0.0.1:8000
```

Requires `.env` at the repo root (13 ZAI keys already saved, gitignored).
Council/Genome/PWA all work even with no keys (offline simulation).

---

## 4) Known notes (honest)

- **Dead keys = slow chat**: only ZAI keys 6,7,8,10,11 are live; a chat
  without a working key takes ~22 s to fall back (5 providers × retries).
  Provider budget/retry control is the next target.
- App version string still reports `10.0.0` (legacy novamind marker);
  `pyproject.toml` is at 1.5.0 — **v2.0.0 version bump + release tag not
  done yet** (waiting on your decision).
- Branch is still `feature/landing-page`, **not merged to main** — the v2.0
  work lives here. Landing page deploy workflow already committed earlier.
- Junk to clean in `web/` when convenient: `fill_env.sh`, `*.bak`,
  `.env.env.bak`.

---

## 5) Your calls (when you're ready)

1. Merge `feature/landing-page` → `main` + release **v2.0.0** (tag + notes)?
2. Archive-formality for the old repos (already archived) re-check?
3. Start the v2.0.1 backlog: provider budget/retry control, RAG, Docker/PyPI?

*Everything below this line ran itself overnight, tested, and pushed — good morning. ☕*