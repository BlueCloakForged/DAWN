# Module: forgescaffold.build_all_caches

## Purpose
Build caches for all projects in the global catalog

## Dependencies (Requires)
- *(none — runs standalone)*

## Produces
- `forgescaffold.cache_batch_report.json`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 300` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |

## Runtime
- **Timeout:** `300s`
