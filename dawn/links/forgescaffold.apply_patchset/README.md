# Module: forgescaffold.apply_patchset

## Purpose
Apply a ForgeScaffold patchset with drift/scope gates and rollback

## Dependencies (Requires)
- `forgescaffold.instrumentation.patchset.json`
- `dawn.project.bundle`

## Produces
- `forgescaffold.apply_report.json`
- `forgescaffold.rollback_patchset.json`
- `forgescaffold.workspace_snapshot.json`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 600` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `600s`
- **Always runs:** yes (not skipped on pipeline skip-mode)
