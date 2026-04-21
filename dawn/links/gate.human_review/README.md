# Module: gate.human_review

## Purpose
Deterministic gate that requires a human_decision.json file to proceed.

## Dependencies (Requires)
- *(none — runs standalone)*

## Produces
- `dawn.gate.decision`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 300` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |

## Runtime
- **Timeout:** `300s`
