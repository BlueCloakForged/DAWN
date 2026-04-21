# Module: spec.requirements_map

## Purpose
Parses SRS to extract canonical requirements tokens

## Dependencies (Requires)
- `dawn.spec.srs`

## Produces
- `dawn.requirements_map`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 600` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `600s`
