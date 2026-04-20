# DAWN Agent Protocol

**Machine-oriented contract for autonomous agents interacting with DAWN**

## Overview

This document defines the interface contract for AI agents executing DAWN pipelines. Agents must follow this protocol to ensure deterministic, auditable execution.

---

## 1. Agent Interface

### 1.1 Entry Point

```bash
python3 -m dawn.runtime.agent \
  --project PROJECT_ID \
  --pipeline PIPELINE_PATH \
  [--profile normal|isolation]
```

### 1.2 JSON Input Format

Agents receive context via `stdin` or context dict:

```json
{
  "project_id": "string",
  "pipeline_id": "string",
  "pipeline_run_id": "uuid",
  "worker_id": "hostname:pid",
  "project_root": "/absolute/path",
  "artifact_index": {
    "artifactId": {
      "path": "/absolute/path",
      "digest": "sha256:...",
      "link_id": "producer_link_id"
    }
  },
  "profile": "normal|isolation",
  "policy": {
    "version": "2.1.0",
    "digest": "sha256:..."
  }
}
```

### 1.3 JSON Output Format

Links must return:

```json
{
  "status": "SUCCEEDED|FAILED",
  "metrics": {
    "custom_metric": "value"
  },
  "errors": {
    "type": "ERROR_CODE",
    "message": "Human-readable message",
    "step_id": "run|validate_inputs|validate_outputs"
  }
}
```

---

## 2. Contract Rules

### 2.1 Artifact Resolution

**MUST** resolve artifacts by `artifactId`, not filename:

```python
# Correct
artifact = context["artifact_index"].get("dawn.project.descriptor")
if artifact:
    with open(artifact["path"]) as f:
        data = json.load(f)

# Incorrect - DO NOT USE
# with open("artifacts/ingest.generic_handoff/project_descriptor.json") as f:
```

### 2.2 Output Writing

**MUST** use the sandbox helper:

```python
# Correct
context["sandbox"].write_json("output.json", data)
context["sandbox"].write_text("report.md", content)

# Incorrect - DO NOT USE
# with open("artifacts/my.link/output.json", "w") as f:
```

### 2.3 Allowed Write Paths

| Path Pattern | Normal Mode | Isolation Mode |
|--------------|-------------|----------------|
| `artifacts/<link_id>/*` | ✓ | ✓ |
| `ledger/*` | ✓ | ✓ |
| `src/*` | Whitelist only | ✗ Never |
| Everything else | ✗ | ✗ |

### 2.4 Idempotency

Links **MUST** be idempotent. Given the same:
- Input artifact digests
- link.yaml digest
- Policy digest

The link **MUST** produce identical outputs (same digests).

---

## 3. Error Handling

### 3.1 Canonical Error Types

```json
{
  "contract_errors": [
    "CONTRACT_VIOLATION",
    "MISSING_REQUIRED_ARTIFACT",
    "PRODUCED_ARTIFACT_MISSING",
    "AMBIGUOUS_ARTIFACT_ORIGIN"
  ],
  "runtime_errors": [
    "RUNTIME_ERROR",
    "POLICY_VIOLATION"
  ],
  "budget_errors": [
    "BUDGET_TIMEOUT",
    "BUDGET_OUTPUT_LIMIT",
    "BUDGET_PROJECT_LIMIT"
  ],
  "schema_errors": [
    "SCHEMA_INVALID"
  ]
}
```

### 3.2 Retry Behavior

Agents **SHOULD** check if errors are retryable:

```python
from dawn.policy import get_policy_loader

loader = get_policy_loader()
if loader.is_error_retryable(error_type):
    # Retry with backoff
    delay = loader.get_backoff_delay(attempt_number)
    time.sleep(delay)
```

---

## 4. Ledger Events

### 4.1 Required Event Fields

Every ledger event **MUST** include:

```json
{
  "timestamp": 1234567890.123,
  "project_id": "string",
  "pipeline_id": "string",
  "link_id": "string",
  "run_id": "uuid",
  "step_id": "link_start|validate_inputs|run|validate_outputs|link_complete",
  "status": "STARTED|SUCCEEDED|FAILED|SKIPPED",
  "metrics": {
    "run_id": "pipeline_run_uuid",
    "worker_id": "hostname:pid"
  }
}
```

### 4.2 Event Sequence

```
link_start (STARTED)
  → validate_inputs (SUCCEEDED|FAILED)
  → run (implicit)
  → sandbox_check (SUCCEEDED|FAILED)
  → validate_outputs (SUCCEEDED|FAILED)
link_complete (SUCCEEDED|FAILED|SKIPPED)
```

---

## 5. Artifact Schemas

### 5.1 Project Descriptor

```json
{
  "$schema": "dawn.project.descriptor",
  "type": "object",
  "required": ["project_id", "name"],
  "properties": {
    "project_id": {"type": "string"},
    "name": {"type": "string"},
    "description": {"type": "string"},
    "version": {"type": "string"}
  }
}
```

### 5.2 Run Summary

```json
{
  "$schema": "dawn.metrics.run_summary",
  "type": "object",
  "required": ["run_id", "worker_id", "status", "timing"],
  "properties": {
    "run_id": {"type": "string", "format": "uuid"},
    "worker_id": {"type": "string"},
    "status": {"enum": ["SUCCEEDED", "FAILED"]},
    "timing": {
      "type": "object",
      "properties": {
        "started_at": {"type": "number"},
        "ended_at": {"type": "number"},
        "duration_ms": {"type": "integer"}
      }
    },
    "links": {
      "type": "object",
      "additionalProperties": {
        "type": "object",
        "properties": {
          "duration_ms": {"type": "integer"},
          "skipped": {"type": "boolean"}
        }
      }
    }
  }
}
```

---

## 6. Security Constraints

### 6.1 Subprocess Restrictions

Allowed commands (normal mode):
- `python3`
- `pytest`
- `git`

Isolation mode further restricts to:
- `python3`
- `pytest`

### 6.2 Input Validation

In isolation mode, only these input extensions are trusted:
- `.json`, `.yaml`, `.yml`, `.md`, `.txt`

---

## 7. Verification

### 7.1 Lockfile Contract

Agents **SHOULD** generate lockfiles for reproducibility:

```bash
python3 -m dawn.runtime.lockfile generate --project PROJECT_ID
```

### 7.2 Release Verification

Before deploying artifacts:

```bash
python3 -m dawn.runtime.verify_release release.zip
# Exit code 0 = verified, 1 = failed, 2 = error
```

---

## 8. Quick Reference

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `DAWN_STRICT_ARTIFACT_ID=1` | Require artifactId in all contracts |

### CLI Commands

| Command | Purpose |
|---------|---------|
| `dawn.runtime.orchestrator` | Run pipelines |
| `dawn.runtime.queue` | Multi-project queue |
| `dawn.runtime.inspect` | View project state |
| `dawn.runtime.lockfile` | Reproducibility |
| `dawn.runtime.prune` | Artifact cleanup |
| `dawn.runtime.verify_release` | Release integrity |

---

*DAWN Agent Protocol v1.0 | Compatible with Policy v2.1.0*
