# Module: forgescaffold.verify_ticket_cache_integrity

## Purpose
Verify ticket cache integrity against ticket_events.jsonl

## Dependencies (Requires)
- *(none — runs standalone)*

## Produces
- `forgescaffold.ticket_cache_integrity_report.json`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 60` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |

## Runtime
- **Timeout:** `60s`
