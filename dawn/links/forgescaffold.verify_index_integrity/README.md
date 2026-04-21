# Module: forgescaffold.verify_index_integrity

## Purpose
Verify evidence index hash chain and optional signed checkpoint

## Dependencies (Requires)
- *(none — runs standalone)*

## Produces
- `forgescaffold.index_integrity_report.json`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 60` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |

## Runtime
- **Timeout:** `60s`
