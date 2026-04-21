# Module: ingest.project_bundle

## Purpose
Registers projects/<id>/inputs as a deterministic bundle manifest

## Dependencies (Requires)
- *(none — runs standalone)*

## Produces
- `dawn.project.bundle`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 300` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |

## Runtime
- **Timeout:** `300s`
