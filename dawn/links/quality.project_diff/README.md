# Module: quality.project_diff

## Purpose
Computes a cryptographic diff between the original bundle and current state.

## Dependencies (Requires)
- `dawn.project.bundle`
- `dawn.project.contract`

## Produces
- `dawn.project.diff`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 300` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `300s`
