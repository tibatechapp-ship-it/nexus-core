# Security Policy

## Supported versions

| Version | Supported |
| ------- | --------- |
| 1.12.x  | Yes       |
| < 1.12  | No        |

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Preferred channel: use GitHub's private reporting —
**Security tab → "Report a vulnerability"**
(https://github.com/tibatechapp-ship-it/nexus-core/security/advisories/new).

Please include: affected version, a minimal reproducer, the impact you observed,
and any suggested fix. We aim to acknowledge reports within 72 hours and to
publish a fix and an advisory once a remediation is available.

## Scope

This repository ships an **offline static security scanner** (8 agents) used by
the framework and the TUI. It is a *defensive* tool: it reads files and reports
findings; it never executes the code it scans. See
[`docs/SECURITY.md`](docs/SECURITY.md) for the scanner's architecture and the
adversarial test suite that guards the framework surface.

### Supply-chain policy

The framework core (`src/{agents,core,patterns,memory,learning,security,tools,tui}`)
imports the **standard library only**. Every third-party import in the wider
surface must be declared in `pyproject.toml`; the adversarial vector
`test_supply_chain_imports_are_stdlib_only` fails the build on any undeclared
(or typosquatted) import.

## Handling secrets

Never commit credentials. `.env` and `*.env` files are git-ignored and the CI
`secret-scan` job rejects any tracked secrets file or hardcoded key pattern.

## Known/Accepted Risks

- **nltk 3.10.3** (transitive dependency, not directly used in codebase): PYSEC-2026-3740. No patched version available for download on this platform (network timeout). nltk is not imported anywhere in `src/` or `tests/`. Risk: low (unused transitive dependency). Action: monitor for patched release; remove if no longer needed.
