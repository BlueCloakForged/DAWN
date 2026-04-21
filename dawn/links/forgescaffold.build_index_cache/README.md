# Module: forgescaffold.build_index_cache

## Purpose
Build a deterministic SQLite cache for evidence_index.jsonl

## Dependencies (Requires)
- *(none — runs standalone)*

## Produces
- `forgescaffold.evidence_index_cache.sqlite`
- `forgescaffold.cache_build_report.json`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 120` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |

## Runtime
- **Timeout:** `120s`
