# LESSONS — nexus-core

## L1: Never trust "done" from an agent
Agents can hallucinate execution. Always verify with:
    git rev-list --count <base>..HEAD
    find ~ -name '<expected-file>'
    git stash list / git reflog -20
    grep -c '<expected-marker>' <expected-file>

## L2: pytest green is not CI green
`make check` is the only gate before tagging. It runs lint + mypy +
pytest + coverage. A green pytest alone is not sufficient evidence.

## L3: `assert X or True` guards nothing
Any assertion ending in `or True` (or `or <truthy-constant>`) is a
vacuous guard. Review all `assert` lines for accidental always-true
conditionals when touching regression tests.

## L4: Additive, not replacement
When wiring a new logger (e.g. request_log) into an existing path,
add it alongside the old one (_metrics.record). Do not replace —
other consumers (dashboard, maintenance) may depend on the old log.

## L5: Tag immutability
Once v*.*.* is pushed to origin + gitlab, never `git tag -f` it.
Ship a v*.*.*+1 hotfix instead.
