# Module: forgescaffold.generate_approval_template

## Purpose
Generate approval template for patchset approval

## Dependencies (Requires)
- `forgescaffold.instrumentation.patchset.json`
- `forgescaffold.review_packet.json`

## Produces
- `forgescaffold.approval_template.json`
- `forgescaffold.approval_instructions.md`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 60` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `60s`
