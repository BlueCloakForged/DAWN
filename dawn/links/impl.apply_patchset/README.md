# Module: impl.apply_patchset

## Purpose
Executes the `impl.apply_patchset` step in the DAWN pipeline.

## Dependencies (Requires)
- `dawn.patchset`
- `dawn.gate.patch_decision`

## Produces
- `dawn.patch.applied`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 600` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `600s`
