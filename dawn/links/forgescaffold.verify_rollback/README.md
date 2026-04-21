# Module: forgescaffold.verify_rollback

## Purpose
Apply rollback patchset and verify workspace hashes

## Dependencies (Requires)
- `forgescaffold.rollback_patchset.json`
- `forgescaffold.workspace_snapshot.json`

## Produces
- `forgescaffold.rollback_report.json`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 600` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `600s`
