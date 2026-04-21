# Module: spec.api_contracts

## Purpose
Executes the `spec.api_contracts` step in the DAWN pipeline.

## Dependencies (Requires)
- `dawn.plan.outline`

## Produces
- `dawn.spec.api`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 600` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `600s`
