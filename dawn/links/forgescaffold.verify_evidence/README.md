# Module: forgescaffold.verify_evidence

## Purpose
Verify evidence signature, trust, and receipt linkage

## Dependencies (Requires)
- `forgescaffold.evidence_manifest.json`
- `forgescaffold.evidence_signature.json`
- `forgescaffold.evidence_receipt.json`
- `forgescaffold.approval_receipt.json`
- `forgescaffold.instrumentation.patchset.json`
- `forgescaffold.rollback_report.json`

## Produces
- `forgescaffold.evidence_verification_report.json`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 120` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `120s`
