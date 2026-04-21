# Module: run.pytest_nonfatal

## Purpose
Execute pytest but don't fail pipeline on test failures (for autofix workflows)

## Dependencies (Requires)
- `dawn.project.bundle`

## Produces
- `dawn.test.execution_report`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 300` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `300s`
