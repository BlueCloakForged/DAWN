# Module: package.release_bundle

## Purpose
Executes the `package.release_bundle` step in the DAWN pipeline.

## Dependencies (Requires)
- `dawn.evidence.pack`
- `dawn.spec.api`
- `dawn.spec.srs`

## Produces
- `dawn.release.bundle`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 600` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `600s`
