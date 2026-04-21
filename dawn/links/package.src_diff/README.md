# Module: package.src_diff

## Purpose
Executes the `package.src_diff` step in the DAWN pipeline.

## Dependencies (Requires)
- `dawn.patch.applied`

## Produces
- `dawn.src.diff`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 600` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `600s`
