# DAWN Operator Guide

**How to run DAWN safely in 15 minutes**

## Quick Start

### 1. Prerequisites

```bash
# Python 3.9+
python3 --version

# Install dependencies
pip install pyyaml filelock jsonschema
```

### 2. Run Your First Pipeline

```bash
# Create a test project
mkdir -p projects/my_first_project/inputs
echo "# My Project Handoff" > projects/my_first_project/inputs/handoff.md

# Run the minimal pipeline
python3 -m dawn.runtime.orchestrator \
  --project my_first_project \
  --pipeline dawn/pipelines/app_mvp.yaml
```

### 3. Check Results

```bash
# Inspect the project
python3 -m dawn.runtime.inspect --project my_first_project

# View artifacts
ls projects/my_first_project/artifacts/
```

---

## Core Concepts

### Links
Self-contained units of work with defined inputs (requires) and outputs (produces).

```yaml
# dawn/links/my.link/link.yaml
apiVersion: dawn.links/v1
kind: Link
metadata:
  name: my.link
spec:
  requires:
    - artifactId: dawn.project.descriptor
  produces:
    - artifactId: my.output
      path: output.json
```

### Pipelines
Ordered sequences of links.

```yaml
# dawn/pipelines/my_pipeline.yaml
pipelineId: my_pipeline
links:
  - id: ingest.generic_handoff
  - id: my.link
```

### Artifacts
Versioned outputs with SHA256 digests tracked in `artifact_index.json`.

### Ledger
Append-only audit log at `projects/<id>/ledger/events.jsonl`.

---

## Common Operations

### Run a Pipeline

```bash
# Basic run
python3 -m dawn.runtime.orchestrator \
  --project PROJECT_ID \
  --pipeline dawn/pipelines/PIPELINE.yaml

# With isolation mode (stricter sandbox)
python3 -m dawn.runtime.orchestrator \
  --project PROJECT_ID \
  --pipeline dawn/pipelines/PIPELINE.yaml \
  --profile isolation
```

### Use the Queue (Multi-Project)

```bash
# Submit projects
python3 -m dawn.runtime.queue submit \
  --project proj1 \
  --pipeline dawn/pipelines/app_mvp.yaml \
  --priority 10

# Check status
python3 -m dawn.runtime.queue status --verbose

# Run queued projects
python3 -m dawn.runtime.queue run
```

### Generate Lockfile (Reproducibility)

```bash
# Generate
python3 -m dawn.runtime.lockfile generate --project PROJECT_ID

# Verify on another machine
python3 -m dawn.runtime.lockfile verify --project PROJECT_ID
```

### Prune Old Artifacts

```bash
# Dry run first
python3 -m dawn.runtime.prune --project PROJECT_ID --dry-run

# Actually prune
python3 -m dawn.runtime.prune --project PROJECT_ID
```

### Verify a Release

```bash
python3 -m dawn.runtime.verify_release release_bundle.zip
```

---

## Policy Configuration

Edit `dawn/policy/runtime_policy.yaml`:

```yaml
# Key settings
budgets:
  per_link:
    max_wall_time_sec: 60    # Timeout per link
    max_output_bytes: 10MB   # Max output size
  per_project:
    max_project_bytes: 1GB   # Max project size

profiles:
  normal:
    allow_src_writes: true
  isolation:
    allow_src_writes: false  # Block all src/ writes

retry:
  max_retries_per_link: 3
  retryable_errors:
    - BUDGET_TIMEOUT
    - RUNTIME_ERROR
```

---

## Error Codes Reference

| Code | Retryable | Description |
|------|-----------|-------------|
| `CONTRACT_VIOLATION` | No | Missing artifactId or invalid contract |
| `MISSING_REQUIRED_ARTIFACT` | No | Input artifact not found |
| `POLICY_VIOLATION` | No | Wrote outside sandbox |
| `BUDGET_TIMEOUT` | Yes | Exceeded wall time |
| `BUDGET_OUTPUT_LIMIT` | No | Output too large |
| `RUNTIME_ERROR` | Yes | Generic execution error |

---

## Troubleshooting

### "Project is BUSY"
Another process holds the lock. Check for stale `.lock` files:
```bash
ls projects/*/.*lock
```

### Timeout Failures
Increase timeout or use normal profile (isolation has 0.5x multiplier):
```bash
--profile normal
```

### Missing Artifacts
Check the artifact index and ledger:
```bash
cat projects/PROJECT/artifact_index.json
tail projects/PROJECT/ledger/events.jsonl
```

---

## Safety Checklist

- [ ] Review `runtime_policy.yaml` before production
- [ ] Use `--profile isolation` for untrusted inputs
- [ ] Generate lockfiles for reproducibility
- [ ] Verify release bundles before deployment
- [ ] Regularly prune old artifacts
- [ ] Monitor ledger for error patterns

---

*DAWN Orchestrator v2.1.0 | Phase 9 Documentation*
