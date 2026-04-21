# Module: package.training_data

## Purpose
Aggregates healing and judgment metrics into DPO training signals

## Dependencies (Requires)
- `dawn.healing.metrics`
- `dawn.judge.score`
- `dawn.project.bundle`

## Produces
- `dawn.training.dpo_signal`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 60` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |
| Transient runtime error (first attempt) | Retries up to `1` time(s) automatically | Inspect link log if all retries exhausted |

## Runtime
- **Timeout:** `60s`
- **Retries:** `1`
