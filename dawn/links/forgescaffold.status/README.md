# Module: forgescaffold.status

## Purpose
Report ForgeScaffold operational status

## Dependencies (Requires)
- *(none — runs standalone)*

## Produces
- `forgescaffold.status.json`
- `forgescaffold.status.md`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 60` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |

## Runtime
- **Timeout:** `60s`
