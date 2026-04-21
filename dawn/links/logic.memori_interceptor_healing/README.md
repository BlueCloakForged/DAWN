# Module: logic.memori_interceptor_healing

## Purpose
Executes the `logic.memori_interceptor_healing` step in the DAWN pipeline.

## Dependencies (Requires)
- `dawn.evolution.transplant`

## Produces
- `memori_interceptor_healed.py`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 600` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `600s`
- **Always runs:** yes (not skipped on pipeline skip-mode)
