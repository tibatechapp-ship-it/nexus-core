# Intelligence evidence contracts

`src.intelligence.contracts` defines a small, versioned payload contract for
intelligence and assurance results. It stores evidence references and digests,
not source contents, so scanners and gates can stay independent.

The first slice intentionally exposes only the contract primitives:

- `CONTRACT_VERSION` (`nexus.intelligence/v1`)
- `ContractError`
- `EvidenceReference`
- `Finding`
- `IntelligenceResult`
- enums: `ResultStatus`, `Severity`, `FindingStatus`

## Guarantees

- All fields are bounded and stripped of control characters.
- `EvidenceReference.sha256` must be a lowercase 64-character SHA-256 digest.
- Confirmed findings require at least one evidence reference.
- Finding and evidence IDs must be unique within a result.
- Findings may only reference evidence included in the same result.
- `from_dict()` rejects unknown fields; `to_dict()` returns detached copies.
- A result must declare a non-empty `scope` of authorized targets.

Out-of-scope engines, gates, capture, replay, and behavior comparison are not
imported by this package in this slice.
