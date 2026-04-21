# Module: correlate.campaign

## Purpose
Cross-project campaign correlation. Scans sibling projects for aipam.findings.ir artifacts and identifies "strong links" where multiple cases share the same dest_ip + MITRE technique.

## Dependencies (Requires)
- `aipam.findings.ir`

## Produces
- `aipam.campaign.correlation`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 120` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `120s`
