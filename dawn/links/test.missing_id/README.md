# Module: test.missing_id

## Purpose
Executes the `test.missing_id` step in the DAWN pipeline.

## Dependencies (Requires)
- `legacy.file`

## Produces
- *(no artifacts produced — side-effect only)*

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 600` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `600s`
