# Module: forgescaffold.generate_review_packet

## Purpose
Generate human-readable review packet for patchset

## Dependencies (Requires)
- `forgescaffold.instrumentation.patchset.json`
- `forgescaffold.system_catalog.json`
- `forgescaffold.dataflow_map.json`
- `forgescaffold.apply_report.json`

## Produces
- `forgescaffold.review_packet.md`
- `forgescaffold.review_packet.json`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 120` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `120s`
