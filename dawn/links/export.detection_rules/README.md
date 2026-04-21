# Module: export.detection_rules

## Purpose
Generates Suricata IDS and Sigma log-detection rules from confirmed forensic findings. Uses LLM-assisted generation when available, with deterministic template fallback.

## Dependencies (Requires)
- `aipam.findings.reviewed`

## Produces
- `aipam.rules.suricata`
- `aipam.rules.sigma`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 300` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `300s`
