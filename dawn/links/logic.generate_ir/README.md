# Module: logic.generate_ir

## Purpose
Executes the `logic.generate_ir` step in the DAWN pipeline.

## Dependencies (Requires)
- *(none — runs standalone)*

## Produces
- `dawn.project.ir`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 600` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |

## Runtime
- **Timeout:** `600s`
