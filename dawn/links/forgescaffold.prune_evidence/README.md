# Module: forgescaffold.prune_evidence

## Purpose
Prune evidence packs based on retention policy

## Dependencies (Requires)
- *(none — runs standalone)*

## Produces
- `forgescaffold.prune_report.json`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 60` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |

## Runtime
- **Timeout:** `60s`
