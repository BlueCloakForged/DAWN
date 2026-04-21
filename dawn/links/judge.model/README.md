# Module: judge.model

## Purpose
Autonomous evaluation link for workflow outputs

## Dependencies (Requires)
- `dawn.project.bundle`
- `dawn.test.execution_report`

## Produces
- `dawn.judge.score`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 120` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |
| Transient runtime error (first attempt) | Retries up to `2` time(s) automatically | Inspect link log if all retries exhausted |

## Runtime
- **Timeout:** `120s`
- **Retries:** `2`
