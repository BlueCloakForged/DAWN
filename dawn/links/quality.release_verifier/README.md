# Module: quality.release_verifier

## Purpose
Audits production artifacts and ledger against the Project Contract.

## Dependencies (Requires)
- `dawn.project.contract`
- `dawn.hitl.approval`
- `aipam.findings.ir`
- `aipam.findings.reviewed`
- `dawn.project.bundle`
- `aipam.campaign.correlation`
- `aipam.analysis.metrics`
- `aipam.rules.suricata`
- `aipam.rules.sigma`

## Produces
- `dawn.quality.release_audit`
- `dawn.trust.receipt`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 300` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `300s`
