# Module: forgescaffold.update_evidence_index

## Purpose
Append evidence index entry for verified runs

## Dependencies (Requires)
- `forgescaffold.evidence_manifest.json`
- `forgescaffold.evidence_signature.json`
- `forgescaffold.evidence_verification_report.json`
- `forgescaffold.approval_receipt.json`
- `forgescaffold.rollback_report.json`
- `forgescaffold.instrumentation.patchset.json`
- `forgescaffold.review_packet.json`

## Produces
- *(no artifacts produced — side-effect only)*

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 60` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `60s`
