# Module: memory.vector_index

## Purpose
Forensic Memory — Vectorizes confirmed findings into a global ChromaDB instance for cross-job recall. Provides the "experience" backbone for the Lead Forensic Investigator chatbot.

## Dependencies (Requires)
- `aipam.findings.reviewed`

## Produces
- `aipam.memory.receipt`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 300` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `300s`
