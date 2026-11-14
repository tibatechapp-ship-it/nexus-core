# MIZAN PR evidence integration

## Current scope

This integration runs the upstream MIZAN engine against the exact PR head
revision whenever a PR targeting `main` is opened, synchronized, reopened,
or marked ready for review.

The scanner job is deliberately read-only:

- It uses the `pull_request` event and grants only `contents: read`.
- Checkout uses the PR head SHA and `persist-credentials: false`.
- It installs MIZAN from the immutable upstream commit recorded in
  `upstream.json`.
- It invokes only `mizan full-scan`; it does not invoke `fix`,
  `repair-request`, `verify-repair`, `approve`, or merge commands.
- It uploads a sanitized JSON evidence artifact and links it in the workflow
  run summary associated with the PR.
- A report is marked incomplete if a scanner, OSV verification, or custom
  policy loading fails. Incomplete reports fail the check; findings alone
  do not masquerade as scanner failures.

## Evidence contract

The adapter emits `nexus.security-evidence.v1` with:

- repository, PR number, exact head/base SHA;
- MIZAN version and scan timestamp;
- per-scanner completion status and incomplete-source list;
- the sanitized full-scan result;
- a SHA-256 digest over canonical JSON, excluding the digest field itself.

A consumer must recompute the digest and compare repository, PR number, and
head SHA with the live PR before using the report. If the head SHA changed,
the report is stale and must be rejected.

## Security boundaries

This workflow does not receive repository secrets or write-capable GitHub
permissions. PR code is inspected as data; it is not imported, built, tested,
or executed by this scan job. The upstream MIZAN package is pinned to a
specific commit rather than a moving branch or tag.

The report is sanitized before artifact upload. Sanitization is a defense in
depth measure, not a guarantee that every possible secret format is known;
artifact access and retention should remain limited.

## Not yet enabled

This change does not yet:

1. publish a PR comment through a separate trusted publisher;
2. connect the evidence artifact to the NEXUS programming agent;
3. launch the agent's isolated repair and test workflow;
4. configure repository branch protection / rulesets to require this check.

Those are separate phases. In particular, the check must be added as a
required status check in repository settings before it can be described as a
mandatory merge gate. No automatic approval, push, or merge is enabled here.
