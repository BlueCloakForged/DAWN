# Module: forgescaffold.append_ticket_event

## Purpose
Append a ticket ledger event

## Dependencies (Requires)
- *(none — runs standalone)*

## Produces
- `forgescaffold.ticket_event_receipt.json`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 30` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |

## Runtime
- **Timeout:** `30s`
