# Module: test.dummy

## Purpose
Executes the `test.dummy` step in the DAWN pipeline.

## Dependencies (Requires)
- *(none — runs standalone)*

## Produces
- `test.dummy.artifact`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 600` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |

## Runtime
- **Timeout:** `600s`
