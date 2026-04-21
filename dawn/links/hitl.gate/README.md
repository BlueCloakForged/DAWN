# Module: hitl.gate

## Purpose
Policy-driven HITL gate bound to bundle_sha256

## Dependencies (Requires)
- `dawn.project.contract`
- `dawn.project.ir`

## Produces
- `dawn.hitl.approval`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- Default timeout / no retries
