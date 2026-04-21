# Module: forgescaffold.obs_define_schema

## Purpose
Emit a unified log envelope schema and observability recommendations

## Dependencies (Requires)
- *(none — runs standalone)*

## Produces
- `forgescaffold.log_envelope.schema.json`
- `forgescaffold.observability_recommendations.md`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 300` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |

## Runtime
- **Timeout:** `300s`
