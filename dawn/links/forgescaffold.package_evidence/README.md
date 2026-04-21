# Module: forgescaffold.package_evidence

## Purpose
Bundle patchset apply evidence into a single folder

## Dependencies (Requires)
- `forgescaffold.instrumentation.patchset.json`
- `forgescaffold.apply_report.json`
- `forgescaffold.rollback_patchset.json`
- `forgescaffold.workspace_snapshot.json`
- `forgescaffold.verification_report.json`
- `forgescaffold.test_results.manifest.json`
- `forgescaffold.approval_receipt.json`
- `forgescaffold.rollback_report.json`

## Produces
- `forgescaffold.evidence_pack.manifest.json`
- `forgescaffold.evidence_manifest.json`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 300` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `300s`
