# Module: validate.requirements_coverage

## Purpose
Validates that requirements in SRS are covered by patchset; fails or gates on gaps.

## Dependencies (Requires)
- `dawn.spec.srs`
- `dawn.requirements_map`
- `dawn.capabilities_manifest`
- `dawn.patchset`

## Produces
- `dawn.requirements_coverage_report`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 600` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `600s`
