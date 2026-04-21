# Module: forgescaffold.status_global

## Purpose
Global operator status across projects

## Dependencies (Requires)
- *(none — runs standalone)*

## Produces
- `forgescaffold.status_global.json`
- `forgescaffold.status_global.md`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 120` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |

## Runtime
- **Timeout:** `120s`
