# Module: impl.generate_patchset

## Purpose
Executes the `impl.generate_patchset` step in the DAWN pipeline.

## Dependencies (Requires)
- `dawn.requirements_map`
- `dawn.spec.srs`
- `dawn.repo.scaffold`

## Produces
- `dawn.patchset`
- `dawn.capabilities_manifest`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 600` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `600s`
