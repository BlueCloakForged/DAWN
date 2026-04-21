# Module: forgescaffold.write_compaction_summary

## Purpose
Write a signed summary for evidence index cache provenance

## Dependencies (Requires)
- *(none — runs standalone)*

## Produces
- `forgescaffold.compaction_summary.json`
- `forgescaffold.compaction_summary.signature.json`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 60` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |

## Runtime
- **Timeout:** `60s`
