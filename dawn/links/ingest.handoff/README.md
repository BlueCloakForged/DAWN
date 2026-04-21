# Module: ingest.handoff

## Purpose
Transforms human docs (bundle) into domain-agnostic IR; parser is pluggable

## Dependencies (Requires)
- `dawn.project.bundle`

## Produces
- `dawn.project.ir`
- `dawn.export.cro`
- `dawn.export.n8n`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 300` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `300s`
