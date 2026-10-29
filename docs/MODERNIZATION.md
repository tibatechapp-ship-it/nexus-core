# MODERNIZATION — chore/modernize (2026-10-30)

Engineer-driven modernization pass. Scope: **safe, high-impact updates only** —
no major-version bumps, no API changes, zero `git push` from this branch without
review. Every change below is verifiable from the branch diff.

---

## 1. Security patches (pip-audit)

**Tooling:** `pip-audit` against all three dependency surfaces.

| Surface | Result |
|---|---|
| `requirements-docker.txt` (container runtime) | ✅ No known vulnerabilities |
| `requirements.txt` (dev mirror) | ✅ No known vulnerabilities |
| `requirements-dev.txt` (CI-only) | ✅ No known vulnerabilities |

**Action:** none required — no CVEs to patch at the current pin set. The
container image also benefits from the dependency removals below (smaller
attack surface: `passlib` and `python-multipart` both had historical CVEs).

## 2. Unused dependencies removed

Verified by exhaustive import scan (`import` / `from` / lazy imports inside
functions / pytest-plugin activation / FastAPI form-parameter usage):

| Package | Was declared in | Evidence of zero usage | Risk |
|---|---|---|---|
| `aiofiles` | `pyproject.toml` novamind extra, `requirements-docker.txt` | 0 imports in `src/`, `main.py`, root scripts, novamind | None |
| `passlib[bcrypt]` | same | 0 imports; only a stale nested `requirements.txt` in the legacy web-platform folder referenced it | None |
| `python-multipart` | same | 0 `Form(`/`File(`/`UploadFile`/`request.form()` in the whole repo | None (FastAPI needs it only when a route parses forms — none exist) |
| `hypothesis` | `pyproject.toml` dev extra, `requirements.txt` | 0 `from hypothesis` / `@given` in `tests/` | None |

**Kept after verification** (looked unused but are not):
`aiosqlite` (SQLAlchemy `sqlite+aiosqlite://` URL driver, loaded dynamically),
`redis` + `psycopg` (readiness probe lazy-imports via `_optional_import`),
`uvicorn` (Dockerfile CMD), `pytest-benchmark` (fixture in
`tests/test_concurrency.py`, `tests/test_phase5_performance.py`),
`pytest-textual-snapshot` + `syrupy` (snapshot fixtures), `pytest-asyncio`
(`asyncio_mode = "auto"`), `pytest-cov` (`--cov` flags).

## 3. Dev experience

Already present and verified working — **no changes needed**:

* `.pre-commit-config.yaml` — ruff on commit; mypy + pytest on push; mirrors
  `scripts/dev_check.sh`.
* `Makefile` — `make test` / `make check` / `make cov` already unified.
* `.editorconfig` — already complete.

**Decision point (يحتاج قرار):** the user brief asked for ruff **and pytest**
before every commit. The pytest hook deliberately stays on `pre-push` because
the suite currently has 45 pre-existing failures (see §4) — moving it to the
commit stage would block every commit until those are triaged. Say the word
and it becomes a commit-stage hook.

## 4. Deploy stack — ROOT CAUSE FOUND AND FIXED

`Deploy stack` (`.github/workflows/deploy.yml`) had **never passed**. The
failed run (40894635972) died at step
`/api/health works without any dependency`: the container never answered.

**Chain of causes, all fixed:**

1. **`main.py:609` — `AttributeError` at import time (the real killer).**
   The startup guard called `GUARD.enabled`, but `AccessGuard` has no
   `enabled` attribute (only `auth_enabled` / `rate_enabled`). Every import of
   `main.py` crashed, so `uvicorn main:app` exited immediately and nothing
   listened on port 8000 — with or without `NEXUS_ALLOW_OPEN=1`.
   **Fix:** `GUARD.enabled` → `GUARD.auth_enabled` (the intended semantic:
   refuse to boot with an empty token unless open mode is explicit).
   This bug also masked **1375 test errors**: `tests/test_health_api.py` and
   every workbench-API test that builds a client via `main.py` could not even
   be set up. After the fix those 1375 execute; 1368 pass, 7 fail (see §5).

2. **`deploy.yml` — lost CI fix (regression).** Commit `9bf04ea` (the
   `/api/review` hardening) accidentally reverted the
   `-e NEXUS_ALLOW_OPEN=1` flag and the debug `docker logs` lines that
   `b94acf7`/`df8b15a` had added. **Fix:** re-applied both, so a failing
   container now dumps its own logs instead of failing silently.

3. **`docker-compose.yml` — guard never reached the compose path.** The
   fail-closed boot guard needs `NEXUS_ALLOW_OPEN` or a token inside the
   container, but compose never passed either, so `Boot the full stack` would
   have refused to start once reachable. **Fix:** added
   `NEXUS_ALLOW_OPEN: ${NEXUS_ALLOW_OPEN:-}` to `x-app-env` (CI smoke passes
   `1`; real deployments should set `NEXUS_AUTH_TOKEN` instead).
   `.env.example` now documents the variable.

4. **`test.yml` — broken YAML.** The `env:` block of the `test` job had
   inconsistent indentation (`NEXUS_ALLOW_OPEN` one level off), which made the
   whole workflow unparseable (it shows up in Actions as
   `.github/workflows/test.yml` with no name). **Fix:** indentation corrected;
   file parses (`yaml.safe_load` verified for all four workflows).

## 5. Pre-existing failures now visible (needs decision — NOT touched)

These were hidden behind the `main.py` import crash. They now run and fail on
their own merits. **No code was changed for them** — they need a product
decision, so per the ground rules they are listed, not fixed:

* `tests/test_build_api.py` (6 tests) — `/api/build`, `/api/craft` responses
  lack the `ok` key the tests expect, and built entries are not returned by
  `GET /api/builds` under `MockProvider`.
* `tests/adversarial/test_security.py::test_deserialization_uses_json_not_pickle`
  — contract drift between the adversarial suite and the current serializer.
* `tests/test_orchestrator_request_log.py` (2), `tests/test_ui_academy.py`
  and ~36 more — same class of latent drift, unchanged by this branch
  (identical list before/after: 38 failed on the pristine tree, the same 38
  here, plus the 7 previously-masked ones above).

**Net test effect of this branch:** errors 1375 → 0, passed 2325 → 3690,
failed 38 → 45 (all 7 additions are the unmasked §5 cases).

## 6. Expected impact

* `Deploy stack` workflow: should go green end-to-end (contracts → smoke →
  readiness → backup) for the first time.
* Container image: 4 fewer packages installed (−~2 MB, smaller audit surface).
* CI: `test.yml` runs again as a real gate on Python 3.11–3.13.
* Runtime: zero behavioral change outside the boot guard, which now behaves
  exactly as its error message always claimed.
