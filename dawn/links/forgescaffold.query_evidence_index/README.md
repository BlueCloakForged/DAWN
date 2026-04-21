# Module: forgescaffold.query_evidence_index

## Purpose
Query evidence index for audit results

## Dependencies (Requires)
- *(none — runs standalone)*

## Produces
- `forgescaffold.evidence_query_results.json`
- `forgescaffold.evidence_query_results.md`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 60` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |

## Runtime
- **Timeout:** `60s`
