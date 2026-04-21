# Module: test.smoke

## Purpose
Executes the `test.smoke` step in the DAWN pipeline.

## Dependencies (Requires)
- *(none — runs standalone)*

## Produces
- `dawn.test.report`
- `dawn.scenarios.report`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 600` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |

## Runtime
- **Timeout:** `600s`
