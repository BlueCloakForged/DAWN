# Module: package.project_bundle

## Purpose
Generic packaging of project artifacts into a ZIP bundle

## Dependencies (Requires)
- `dawn.project.descriptor`
- `dawn.project.ir`
- `validate.project_handoff.report`
- `dawn.project.export.primary`
- `dawn.project.export.workflow`

## Produces
- `package.project_bundle.zip`
- `package.project_bundle.manifest`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 300` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `300s`
