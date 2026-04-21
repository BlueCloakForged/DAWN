# Module: analyze.forensic_cot

## Purpose
Bridge AIPAM's ForensicEngine (Chain-of-Thought) into the DAWN runtime. Performs two-stage LLM forensic analysis on parsed network flows and produces structured findings with MITRE ATT&CK mappings. Guardrail violations (hallucinated flow IDs) are logged to the ledger.

## Dependencies (Requires)
- `aipam.flow.ir`
- `dawn.project.bundle`

## Produces
- `aipam.findings.ir`
- `aipam.analysis.metrics`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 600` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `600s`
