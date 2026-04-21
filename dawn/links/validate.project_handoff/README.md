# Module: validate.project_handoff

## Purpose
Generic validation gate for project descriptor and IR

## Dependencies (Requires)
- `dawn.project.descriptor`
- `dawn.project.ir`
- `dawn.project.export.primary`
- `dawn.project.export.workflow`

## Produces
- `validate.project_handoff.report`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 300` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `300s`
