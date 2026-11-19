# Mission Execution Policy

NEXUS CORE does not infer permission to execute repository code. Every new mission run must carry an explicit execution policy.

## Execution modes

### Trusted-local process mode

Use this only when the operator already trusts the repository and the host environment:

```bash
org mission --title "..." --objective "..." --repo ./repo \
  --execution-mode process --trust-local
```

The `--trust-local` flag is an explicit trust assertion, **not an operating-system sandbox**. Do not use this mode for untrusted repositories.

### Approved container mode

Container execution requires a mission-bound, human-approved record and an immutable image reference:

```bash
# 1. Create the mission without running it.
org create-mission --title "..." --objective "..." --repo ./repo

# 2. Request approval for the exact digest-pinned image.
org request-run-approval <mission-id> \
  --container-image registry.example/nexus-runner@sha256:<64-hex-digest>

# 3. A human reviews and decides the approval.
org approve <approval-id> --yes --by <operator-id>

# 4. Execute the same mission with the same image and approval.
org mission --mission-id <mission-id> \
  --title "..." --objective "..." --repo ./repo \
  --execution-mode container --container-enabled \
  --container-image registry.example/nexus-runner@sha256:<same-64-hex-digest> \
  --approval-id <approval-id>
```

If the mission was created with `--max-output-tokens`, pass the same value to the final `mission` command. Mission identity, repository, objective, and budget are immutable for this approval flow.

The approval is bound to the mission ID and exact image string. A pending, rejected, missing, or differently bound approval fails closed. Container mode uses the configured rootless, networkless container runner; approval does not replace host/container hardening.

## REST workflow

All mutating endpoints require `Authorization: Bearer $ORG_OPERATOR_TOKEN`.

1. `POST /org/missions` creates a mission.
2. `POST /org/missions/{mission_id}/approvals/run-untrusted` requests image-bound approval.
3. `POST /org/approvals/{approval_id}/decide` records the human decision.
4. `POST /org/missions/{mission_id}/run` executes the mission with an explicit `execution_mode` policy.
5. `POST /org/missions/{mission_id}/resume` requests an audited resume with `actor`, `reason`, and optional `expected_repo_root`.

The API returns a conflict for a mission that is no longer in the `created` state. Resume is a separate, explicit operation; it restores the immutable checkpoint policy and does not accept a replacement execution policy.

## Resume and recovery

A resume is never an automatic retry. The operator must supply an identity and a reason:

```bash
org resume <mission-id> --by <operator-id> \
  --reason "Reviewed checkpoint and approved recovery" \
  --expected-repo-root /absolute/path/to/repo
```

The expected repository root is optional when the caller cannot supply an independent root, but should be provided when available. Resume validates the saved checkpoint, repository state, original execution policy, and durable task state before continuing. Container approvals are revalidated against the original mission and exact image.

## Security invariants

- No execution policy means no execution.
- Process mode requires explicit trusted-local acknowledgement and is not a security boundary.
- Container mode requires explicit enablement, a digest-pinned image, and a human approval bound to the mission and image.
- Unknown policy fields and unsupported schema versions are rejected.
- The execution policy cannot be changed between checkpoints.
- The original revision-loop limit is restored on resume.
- A mission cannot be run twice through the new-run endpoint; recovery uses the audited resume path.
- No command in this workflow merges a pull request or deploys software.
