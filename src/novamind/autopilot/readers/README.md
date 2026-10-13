# `novamind.autopilot.readers` — issues → structured tasks

Turns a provider-shaped :class:`~src.novamind.autopilot.scm.base.Issue` into a
normalised, ranked :class:`Task` the rest of the autopilot can reason about.
Read-only, standard-library only, and fully offline-testable (no clock, no
network except through the injected SCM).

```text
Issue (scm)                       Task (readers)
┌──────────────────┐              ┌───────────────────────────────────────┐
│ title, body,      │  IssueReader │ kind    bug|feature|docs|question|chore│
│ labels, author,   │ ───────────▶ │ priority p0..p3|none                   │
│ state, url        │  classify.*  │ areas, criteria, references            │
└──────────────────┘              │ needs_info, fingerprint                 │
                                   └───────────────────────────────────────┘
        fetch                          dedupe → select → rank
```

## Public API

| Symbol | What it does |
|---|---|
| `IssueReader(scm, *, min_body_words=8)` | Fetch issues via any `SCM` and map them to `Task`s |
| `.read(labels=, state=, limit=)` | List → `list[Task]` (upstream order preserved) |
| `.read_one(number)` | One issue → `Task` |
| `.collect(kinds=, priority_max=, areas=, include_needs_info=)` | `read` → `dedupe` → `select` → `rank` in one call |
| `dedupe(tasks)` | Drop tasks sharing a `fingerprint` (first wins) |
| `select(tasks, …)` | Filter by kind / priority ceiling / areas / triage state |
| `rank(tasks)` | Sort most-urgent first (priority, kind, title) |
| `Task` | Frozen value object: `to_dict()`, `summary()`, `.ready` |
| `classify_kind/priority`, `extract_areas/criteria/references`, `needs_more_info` | The pure transforms (unit-tested in isolation) |

## How a task is read

* **kind** — explicit labels win (`bug`, `enhancement`, `docs`, `question`,
  `chore`), with a title/body keyword fallback; `type:`/`kind/` prefixes are
  stripped (`type: bug` == `kind/bug` == `bug`).
* **priority** — from labels: `p0`/`critical`/`blocker` → p0 … `p3`/`low` → p3,
  plus `priority:high` and bare `priority:2`. No signal → `none`.
* **areas** — `area:auth`, `component-ui`, `module/api` labels **and** file
  paths found in the text (`src/core/router.py`).
* **criteria** — markdown checkboxes (`- [ ]` / `- [x]`) anywhere; if none, the
  bullet list under an *acceptance criteria* / *definition of done* heading.
* **references** — URLs and `#NNN` cross-links.
* **needs_info** — explicit triage label, or no criteria **and** a body shorter
  than `min_body_words` meaningful words. Conservative by design.
* **fingerprint** — a stable hash of the *normalised title + kind*, ignoring
  platform and number, so the same issue filed twice collapses to one task.

## Gate

```bash
COVERAGE_RCFILE=coverage-autopilot.ini \
  python -m pytest tests/test_autopilot_*.py \
  --cov=src/novamind/autopilot --cov-report=term-missing --cov-fail-under=95
# → 186 tests, 100% coverage
```
