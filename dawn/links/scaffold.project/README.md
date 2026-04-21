# Module: scaffold.project

## Purpose
Creates a deterministic project folder scaffold.

## Dependencies (Requires)
- *(none — runs standalone)*

## Produces
- `dawn.scaffold.manifest`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 300` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |

## Runtime
- **Timeout:** `300s`
