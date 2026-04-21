# Module: hitl.healing_gate

## Purpose
HITL gate for exhausted healing cycles

## Dependencies (Requires)
- `dawn.healing.exhausted_gate`

## Produces
- `dawn.hitl.healing_resolution`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 0 # Manual gate, no timeout` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `0 # Manual gate, no timeouts`
