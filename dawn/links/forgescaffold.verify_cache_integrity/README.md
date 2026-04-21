# Module: forgescaffold.verify_cache_integrity

## Purpose
Verify evidence index cache integrity against raw JSONL

## Dependencies (Requires)
- *(none — runs standalone)*

## Produces
- `forgescaffold.cache_integrity_report.json`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 120` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |

## Runtime
- **Timeout:** `120s`
