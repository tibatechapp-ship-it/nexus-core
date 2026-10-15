# `novamind.autopilot` — the self-managing repository

Turns nexus-core from "an agent framework" into a **platform that manages its
own repositories**: it reads issues, consults The Council for a verdict, and
(later) opens reviewed changes — on GitHub *and* GitLab through one interface.

Everything here is **standard library only** and runs on a phone (Termux).

## Layered design

```
   ┌──────────────────────────────────────────────────────────────┐
   │  autopilot                                                    │
   │                                                               │
   │   scm/        provider-agnostic read/write access  ◀── Slice 1 │
   │    ▲            GitHubSCM · GitLabSCM · transports             │
   │    │                                                           │
   │   readers/    turn raw issues into structured work ◀── Slice 2 │   │    ▲                                                           │
   │   council bridge   debate + consensus on a task     ◀── Slice 3 │
   │    ▲                                                           │
   │   … writing, reviewing, tasks, training            ◀── later   │
   └──────────────────────────────────────────────────────────────┘
        read-only slices ─────────────▶ │ ◀───────────── write slices
```

Slices 1–3 are **read-only by construction** (`SCMWriter` is declared but not
implemented), so the autopilot cannot mutate a repository until the write slices
deliberately add that capability.

## Slices

| Slice | Scope | Status |
|---|---|---|
| 1 | SCM abstraction (GitHub + GitLab, read-only) | ✅ shipped |
| 2 | Issue reader (fetch → parse → structured task) | ✅ shipped |
| 3 | Council bridge (debate + consensus on a task) | ⏳ next |
| 4 | Licensing (ranks, certificates, permissions) | planned |
| 5 | Writer (comment / open change) | planned |

## Modules

- **`scm/`** — provider-agnostic source control. See [`scm/README.md`](scm/README.md).
- **`readers/`** — issues → structured, ranked tasks. See
  [`readers/README.md`](readers/README.md).

## Principles

- **Just-in-time** — build only what a slice needs (KISS > clever).
- **Read before write** — write capability is structurally absent until its slice.
- **Measure, don't claim** — numbers come from deterministic tests, not prose.
- **Offline & stdlib-only** — the whole layer runs and is tested on a phone.

## Quality gate

```bash
COVERAGE_RCFILE=coverage-autopilot.ini \
  python -m pytest tests/test_autopilot_*.py \
  --cov=src/novamind/autopilot --cov-report=term-missing --cov-fail-under=95
```

Current: **186 tests, 100% coverage** on `src/novamind/autopilot`; repo-wide
`ruff check .`, `mypy`, and the annotation check stay green.
