# Module: aipam.extract

## Purpose
Runs Zeek and Suricata on bundled PCAPs within the DAWN sandbox, parses logs into the structured JSON IR that analyze.forensic_cot expects, and publishes aipam.flow.ir.

## Dependencies (Requires)
- `dawn.project.bundle`

## Produces
- `aipam.flow.ir`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 600` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `600s`
