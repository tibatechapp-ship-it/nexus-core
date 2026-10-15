# `novamind.autopilot.scm` — provider-agnostic source control

One neutral interface for every hosting platform (GitHub, GitLab, and — later —
the Gitea family). The autopilot is written **once** against `SCM` and runs on
any backend.

Slice 1 is **read-only**: the write surface (`SCMWriter`) is *declared* but not
implemented, so no code in this layer can mutate a repository.

## Architecture

```
                    ┌──────────────────────────────────────────┐
   autopilot  ─────▶│  SCM (Protocol)  — read-only interface    │
   workers          │    whoami() list_issues() get_issue()     │
                    │    list_changes() get_change()            │
                    └───────────────┬──────────────────────────┘
                                    │  isinstance(adapter, SCM)
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
             ┌────────────┐                 ┌────────────┐
             │ GitHubSCM  │                 │ GitLabSCM  │   (adapters)
             └─────┬──────┘                 └─────┬──────┘
                   │   both speak the same Transport protocol
                   ▼                               ▼
        ┌───────────────────────────────────────────────────┐
        │  Transport (Protocol):  request(method, url, ...)  │
        ├───────────────────────────────────────────────────┤
        │  CachingTransport      (GET cache, TTL, stats)     │  ← stackable
        │  RateLimitedTransport  (throttle + 429 back-off)   │
        │  UrllibTransport       (production, stdlib only)   │
        │  RecordingTransport    (offline test double)       │
        └───────────────────────────────────────────────────┘
```

Transports are composable, e.g.:

```python
from novamind.autopilot.scm import (
    GitHubSCM, UrllibTransport, CachingTransport, RateLimitedTransport, RateLimiter,
)

base = CachingTransport(UrllibTransport(), ttl=60.0)
limited = RateLimitedTransport(base, RateLimiter(rate=5, period=1.0))
github = GitHubSCM(token, repo="owner/name", transport=limited)
issues = github.list_issues(labels=("bug",))
print(base.stats().hit_rate)  # real, measured
```

## API

| Method | Returns | Notes |
|---|---|---|
| `whoami()` | `str` | authenticated login / username |
| `list_issues(*, labels=(), state="open", limit=20)` | `list[Issue]` | GitHub pull requests are filtered out |
| `get_issue(number)` | `Issue` | per-repository number |
| `list_changes(*, state="open", limit=20)` | `list[Change]` | pull requests / merge requests |
| `get_change(number)` | `Change` | per-repository number |

`Issue` / `Change` are frozen, provider-neutral dataclasses — the same fields
regardless of platform (contract tests enforce this).

## Provider differences absorbed here

| Concern | GitHub | GitLab |
|---|---|---|
| per-project number | `number` | `iid` |
| body field | `body` | `description` |
| author | `user.login` | `author.username` |
| state | `open` | `opened` → normalised to `open` |
| project path | `owner/name` | `group%2Fproject` |
| pagination | `Link: …; rel="next"` | `X-Next-Page` |
| auth header | `Authorization: Bearer` | `PRIVATE-TOKEN` |

## Error model

All failures funnel through one mapping (`error_for_status`):

```
0 / 5xx        → TransientError   (retry)
404            → NotFoundError
401 / 403      → AuthError
429 / 403+Retry-After → RateLimitError (carries .retry_after)
malformed body → TransientError   (never leaks JSONDecodeError)
```

## Measured behaviour (not claims)

Every number below is asserted by a deterministic test with an injected clock —
no sleeps, no network:

| Property | Measured | Test |
|---|---|---|
| rate limiter spacing | `rate=5/s, burst=1` → 11 calls span **2.00 s** | `test_rate_limiter_measured_throughput` |
| cache effectiveness | 10 identical GETs → **1 upstream call, 9 saved, hit_rate 0.90** | `test_caching_transport_measured_api_calls_saved` |

The marketing figures once floated for caching/batching ("80% / 90%") are **not
used** — only the numbers above are measured.

## Run the tests & gate

```bash
COVERAGE_RCFILE=coverage-autopilot.ini \
  python -m pytest tests/test_autopilot_scm_*.py \
  --cov=src/novamind/autopilot --cov-report=term-missing --cov-fail-under=95
# ruff check . ; mypy src/novamind/autopilot/scm/*.py  (pass explicit files)
```

All tests are offline; `RecordingTransport` stands in for the network.
