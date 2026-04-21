# Module: forgescaffold.query_global_evidence

## Purpose
Query evidence across projects using global catalog

## Dependencies (Requires)
- *(none — runs standalone)*

## Produces
- `forgescaffold.evidence_global_query_results.json`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 120` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |

## Runtime
- **Timeout:** `120s`
