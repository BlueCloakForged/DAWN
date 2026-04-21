# Module: forgescaffold.sign_evidence

## Purpose
Sign evidence manifest and approval receipt

## Dependencies (Requires)
- `forgescaffold.evidence_manifest.json`
- `forgescaffold.approval_receipt.json`

## Produces
- `forgescaffold.evidence_signature.json`
- `forgescaffold.evidence_receipt.json`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 120` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `120s`
