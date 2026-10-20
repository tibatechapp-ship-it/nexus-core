# Security Audit — STRIDE — nexus-core

**Date:** 2026-10-20
**Scope:** unified gateway + framework + workbench + novamind + training/maintenance
**Method:** STRIDE (6 categories), executable PoC per control
**Artifacts:** `docs/security/threat-model-STRIDE.md`,
`tests/security/stride/` (29 vectors), `tests/test_stride_fixes.py` (23 regressions)

---

## 1. Executive summary

The audit produced **3 real findings** across 2 categories and verified **19
controls** with executable PoCs. All three findings are **fixed**, each with a
regression test in the standard suite.

| Severity | Count | Fixed | Accepted |
|----------|-------|-------|----------|
| HIGH | 2 | 2 | 0 |
| MEDIUM | 1 | 1 | 0 |
| LOW | 0 | 0 | 0 |
| Accepted gaps (documented) | 3 | — | 3 |

**Posture:** the security-critical boundaries (auth compare, tool sandbox,
builder write gate, guard method coverage, secret scanner, rate limiter) all
**held** under attack. The failures were at **input-validation boundaries** and
**diagnostic output**, not in the core controls.

**PoC suite result after fixes:** **29 / 29 held** (0 broken), every category at
**100% resilience**.

---

## 2. Findings

### F1 — HIGH — Tool executor read the live `.env` (Information Disclosure)

* **Vector:** `LocalToolExecutor.execute(ToolCall("read", {"path": ".env"}))`
* **Observed:** `ok=True`, returning 2486 bytes of the real `.env`, including
  `OLLAMA_API_KEY=…` and other provider credentials.
* **Root cause:** `_resolve` confined the path to the workspace root but did not
  distinguish a *secret* inside the root from an ordinary file. `grep`
  additionally surfaced the file's contents via `_walk_text_files`.
* **Impact:** any agent/tool path that can reach the executor could exfiltrate
  every provider key — billing and account risk.
* **Fix:** `is_sensitive_file()` in `src/tools/executor.py` (exact names +
  `.env.*` prefix + `.pem/.key/.p12/.pfx/.keystore` suffixes) consulted in both
  `_resolve` and `_walk_text_files`. `.env.example` stays readable (names only).
* **Regression:** `tests/test_stride_fixes.py` (I4 group) +
  `tests/security/stride/test_info_disclosure.py::test_i4_*`
* **Verified:** executor now refuses `.env`, `.env.bak`, `id_rsa`, `cert.pem`,
  `secrets.json`, `.git-credentials`; `grep` no longer surfaces the value.

### F2 — HIGH — Hostile `genome_import` payload → HTTP 500 (Tampering + DoS)

* **Vector:** `POST /api/genome/import {"agents": "not-a-list"}`, or a list of
  non-dicts, or a dict with a non-numeric field.
* **Observed:** `AttributeError: 'str' object has no attribute 'get'` (and, after
  the first fix, `ValueError: invalid literal for int()` on `"generation": "bad"`)
  → unhandled → 500.
* **Root cause:** `SessionStore.genome_import` iterated its argument and
  `.get(…)`-ed every element with no shape/type check; numeric fields were
  coerced with a bare `int()/float()`.
* **Impact:** a non-privileged caller (when the token is unset) can produce a
  500 storm; import state is left in an inconsistent position.
* **Fix:** validate the container at the boundary (non-list → empty import),
  skip non-dict rows, coerce numerics via `_as_int` / `_as_float` (never raise).
* **Regression:** `tests/test_stride_fixes.py` (T3 group) +
  `tests/security/stride/test_tampering.py::test_t3_*` +
  `tests/security/stride/test_dos.py::test_d2_*`

### F3 — MEDIUM — `/api/diag` disclosed absolute paths + raw `sys.path`

* **Vector:** anonymous `GET /api/diag` (a read — not gated).
* **Observed:** `loaded_from: /data/data/com.termux/files/home/nexus-core/nexus_agent.py`
  and `sys_path_head: [ …entries… ]`.
* **Root cause:** the diagnostic endpoint returned internals without bounding
  them to a non-reconnaissance shape.
* **Impact:** filesystem-layout reconnaissance (install root, interpreter
  environment) with no authentication.
* **Fix:** `loaded_from` → bare filename; `sys.path` → entry **count**
  (`sys_path_entries`). The route inventory stays (public via the spec).
* **Regression:** `tests/security/stride/test_info_disclosure.py::test_i1_*` +
  `tests/test_stride_fixes.py::test_i1_diag_has_no_absolute_paths`

---

## 3. Controls verified (held)

| Category | Controls verified | Result |
|----------|-------------------|--------|
| Spoofing | constant-time compare · blank-token refusal · exact header · agent-id lookup · anti-`X-Forwarded-For` | 5/5 held |
| Tampering | traversal confinement · craft write gate · hostile import (fixed) · pure reads · sandbox confinement | 5/5 held |
| Repudiation | attributable audit rows · explicit audit-off · no token in audit · traceable votes | 4/4 held |
| Information Disclosure | diag bounded (fixed) · no key echo · scanner detects · no tracked secrets + executor deny-list (fixed) · status hides token | 5/5 held |
| Denial of Service | rate-limiter cap · import no-crash (fixed) · batch clamp · pathological input · bounded rejects | 5/5 held |
| Elevation of Privilege | traversal denied · allow-list only · write gate · all mutating verbs gated · sandbox cwd | 5/5 held |

---

## 4. Accepted, documented gaps

| ID | Gap | Why accepted | Follow-up |
|----|-----|--------------|-----------|
| W-R1 | Audit OFF by default | Zero-config local use; enabling needs an operator decision | Documented opt-in |
| W-D1 | No global request-body size cap | Needs a middleware over every route; medium effort | v1.33 candidate |
| W-S1 | Tokenless gateway accepts any caller | Loopback-first design | Warn if bound publicly without a token |

---

## 5. Verification (reproduce)

```bash
# PoC suite — the finding-detectors
python -m pytest tests/security/stride/ -q            # 29 passed, 0 broken

# Standard-suite regression guards for the fixes
python -m pytest tests/test_stride_fixes.py -q        # 23 passed

# Whole quality gate
make check                                            # 3501 passed, 1 skipped
```

Gates at the tip of this work: **ruff clean · mypy 184 · annotations 184 ·
`pytest --cov` 3501 passed, 1 skipped** (floor 95).

---

## 6. Conclusion

The dangerous boundaries held; the failures were at input validation and
diagnostic output. All three findings are fixed with regression tests, all 29
PoC vectors pass, and the three remaining gaps are explicit, low-risk, and
documented rather than hidden. The threat model in
`docs/security/threat-model-STRIDE.md` is the durable reference; the PoC suite in
`tests/security/stride/` is the executable check that the boundaries stay closed.
