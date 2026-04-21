# Module: validate.json_artifacts

## Purpose
Validates JSON artifacts at boundary - parseability and minimal schema

## Dependencies (Requires)
- *(none — runs standalone)*

## Produces
- *(no artifacts produced — side-effect only)*

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 600` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |

## Runtime
- **Timeout:** `600s`
