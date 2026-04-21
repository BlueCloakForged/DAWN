# Module: forgescaffold.gate_patchset_approval

## Purpose
HITL gate for patchset approval

## Dependencies (Requires)
- `forgescaffold.instrumentation.patchset.json`
- `forgescaffold.review_packet.json`

## Produces
- `forgescaffold.approval_receipt.json`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 120` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `120s`
