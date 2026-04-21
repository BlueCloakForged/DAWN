# Module: handoff.receptor

## Purpose
Executes the `handoff.receptor` step in the DAWN pipeline.

## Dependencies (Requires)
- *(none — runs standalone)*

## Produces
- `dawn.evolution.transplant`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 600` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |

## Runtime
- **Timeout:** `600s`
- **Always runs:** yes (not skipped on pipeline skip-mode)
