# Module: package.project_report

## Purpose
Generates HTML project report with run metrics, budgets, and policy info

## Dependencies (Requires)
- `dawn.project.descriptor`
- `dawn.src.diff`
- `dawn.metrics.run_summary`

## Produces
- `dawn.project.report`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 600` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `600s`
