# Module: aipam.ingest.pcap

## Purpose
Source-agnostic PCAP ingest link. Validates PCAP files from inputs/, runs Zeek/Suricata for feature extraction, and produces the unified aipam.flow.ir intermediate representation consumed by all downstream analysis links. Reads sensitivity from the project contract.

## Dependencies (Requires)
- *(none — runs standalone)*

## Produces
- `aipam.flow.ir`
- `dawn.project.bundle`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 600` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |

## Runtime
- **Timeout:** `600s`
- **Always runs:** yes (not skipped on pipeline skip-mode)
