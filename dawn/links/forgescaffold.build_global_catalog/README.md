# Module: forgescaffold.build_global_catalog

## Purpose
Build a deterministic global catalog of per-project evidence

## Dependencies (Requires)
- *(none — runs standalone)*

## Produces
- `forgescaffold.global_catalog.json`
- `forgescaffold.global_catalog.signature.json`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 120` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |

## Runtime
- **Timeout:** `120s`
