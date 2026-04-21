# Module: simulate.traffic_pattern

## Purpose
Purple Team Adversary Emulation — Generates safe, non-malicious Scapy-based Python scripts that replicate the timing, port usage, and payload structure of confirmed malicious findings.  Used for security sensor testing and closed-loop validation.

## Dependencies (Requires)
- `aipam.findings.reviewed`
- `aipam.flow.ir`

## Produces
- `aipam.simulation.py`
- `aipam.simulation.manifest`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 600` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `600s`
