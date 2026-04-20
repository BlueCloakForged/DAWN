# DAWN Quick Start Guide

Get up and running with **DAWN (Deterministic Auditable Workflow Network)** in 5 minutes.

---

## Prerequisites

- Python 3.8+
- Virtual environment activated
- Dependencies installed (see [INSTALL.md](INSTALL.md))

```bash
# Quick check
python3 -c "from dawn.runtime.orchestrator import Orchestrator; print('✅ Ready')"
```

---

## 1. Understanding DAWN Basics

### What is DAWN?

DAWN executes **deterministic pipelines** composed of **links** (autonomous units of work):

- **Links**: Self-contained tasks (build, test, validate) with explicit `requires`/`produces` contracts
- **Pipelines**: Ordered chains of links defined in YAML
- **Projects**: Isolated workspaces containing artifacts and execution logs

### Key Concepts

| Concept | Description |
|---------|-------------|
| **Link** | Atomic unit of work with contract enforcement |
| **Pipeline** | YAML definition of link execution order |
| **Artifact** | Output file produced by a link (e.g., build results, reports) |
| **Ledger** | Immutable audit trail of all execution events |
| **Artifact Index** | Logical mapping of `artifactId → {path, digest, producer}` |

---

## 2. Basic Usage

### Run a Pipeline

```bash
# Navigate to DAWN directory
cd ~/DAWN

# Execute a pipeline for a project
python3 -m dawn.runtime.main \
  --project my_app \
  --pipeline dawn/pipelines/default.yaml
```

**What happens?**
1. Creates `projects/my_app/` directory
2. Executes each link in the pipeline sequentially
3. Produces artifacts in `projects/my_app/artifacts/<link_id>/`
4. Logs events to `projects/my_app/ledger/events.jsonl`
5. Generates `artifact_index.json` and `pipeline.yaml`

### View Execution Results

```bash
# View execution summary
python3 -m dawn.runtime.summary projects/my_app/ledger/events.jsonl

# View recent events
tail -n 20 projects/my_app/ledger/events.jsonl

# List generated artifacts
ls -R projects/my_app/artifacts/
```

---

## 3. Common Commands

### Create a New Project

```bash
# Using the 'new' module
python3 -m dawn.runtime.new my_new_project

# This creates:
# - projects/my_new_project/
# - projects/my_new_project/src/
# - projects/my_new_project/.gitignore
```

### Inspect Available Links

```bash
# List all registered links
python3 -c "from dawn.runtime.registry import Registry; \
r = Registry('dawn/links'); r.discover_links(); \
print('\n'.join(sorted(r.links.keys())))"
```

### Check Link Details

```bash
# View a specific link's contract
cat dawn/links/build.ci/link.yaml
```

### Run with Isolation Profile

```bash
# Use stricter isolation mode
python3 -m dawn.runtime.main \
  --project secure_app \
  --pipeline dawn/pipelines/default.yaml \
  --profile isolation
```

**Isolation mode** enforces:
- No writes to `src/` directory
- Artifacts-only outputs
- Stricter sandbox enforcement

---

## 4. Example Workflows

### Example 1: Simple Build Pipeline

```bash
# 1. Create project
python3 -m dawn.runtime.new demo_app

# 2. Add source files
echo 'print("Hello DAWN")' > projects/demo_app/src/main.py

# 3. Run basic pipeline
python3 -m dawn.runtime.main \
  --project demo_app \
  --pipeline dawn/pipelines/basic.yaml

# 4. Verify
python3 -m dawn.runtime.summary projects/demo_app/ledger/events.jsonl
```

### Example 2: Full SDLC Pipeline with Quality Gates

```bash
# Run comprehensive pipeline
python3 -m dawn.runtime.main \
  --project production_app \
  --pipeline dawn/pipelines/default_app_dev.yaml

# Check quality gate results
cat projects/production_app/artifacts/quality.gates/quality_report.json
```

### Example 3: Custom Pipeline with Overrides

Create `custom_pipeline.yaml`:

```yaml
pipelineId: custom_build
links:
  - id: build.ci
    config:
      timeout_sec: 600
  - id: quality.gates
    when:
      condition: on_success(build.ci)
  - id: validation.self_heal
    when:
      condition: on_failure(quality.gates)
```

Run it:

```bash
python3 -m dawn.runtime.main \
  --project custom_app \
  --pipeline custom_pipeline.yaml
```

---

## 5. Understanding Artifacts

### Artifact Structure

```
projects/my_app/
├── artifacts/
│   ├── build.ci/
│   │   └── build_output.json
│   ├── quality.gates/
│   │   └── quality_report.json
│   └── dawn.metrics.run_summary/
│       └── run_summary.json
├── ledger/
│   └── events.jsonl
├── artifact_index.json
└── pipeline.yaml
```

### Artifact Index

The `artifact_index.json` maps logical IDs to physical files:

```json
{
  "build.ci.output": {
    "path": "projects/my_app/artifacts/build.ci/build_output.json",
    "digest": "sha256:abc123...",
    "link_id": "build.ci",
    "run_id": "550e8400-e29b-41d4-a716-446655440000",
    "created_at": "2026-01-18T01:23:45Z"
  }
}
```

---

## 6. Advanced Features

### Enable Strict Artifact Mode

```bash
# Enforce artifactId for all requires/produces
export DAWN_STRICT_ARTIFACT_ID=1

python3 -m dawn.runtime.main \
  --project strict_app \
  --pipeline dawn/pipelines/default.yaml
```

### Resource Budgets

Edit `dawn/policy/runtime_policy.yaml`:

```yaml
budgets:
  per_project:
    max_project_bytes: 500000000  # 500 MB
  per_link:
    max_output_bytes: 50000000    # 50 MB
    max_wall_time_sec: 300        # 5 minutes
```

Budget violations will fail the pipeline with detailed errors.

### Conditional Execution

Links can run conditionally based on upstream status:

```yaml
links:
  - id: build.ci
  - id: deploy
    when:
      condition: on_success(build.ci)
  - id: rollback
    when:
      condition: on_failure(deploy)
```

---

## 7. Verification and Testing

### Run Built-in Verification

```bash
# Verify Phase 3 features
python3 scripts/verify_phase3.py

# Verify Phase 6 features
python3 scripts/verify_phase6.py
```

### Inspect Ledger Events

```bash
# View all events as JSON
cat projects/my_app/ledger/events.jsonl | jq '.'

# Filter by link
cat projects/my_app/ledger/events.jsonl | jq 'select(.link_id=="build.ci")'

# Filter by status
cat projects/my_app/ledger/events.jsonl | jq 'select(.status=="FAILED")'
```

---

## 8. T2T Integration (Text-to-Topology)

DAWN includes a **T2T agent** for document processing and network topology generation.

### Start T2T Web UI

```bash
cd T2T
streamlit run app.py
```

Access at: http://localhost:8501

### Features

- PDF/DOCX document processing
- Network topology extraction
- Visual representation with Cytoscape
- CRO (Cyber Range Orchestrator) export

---

## 9. Troubleshooting

### Pipeline Fails: Missing Artifact

**Error**: `MISSING_REQUIRED_ARTIFACT: build.ci.output`

**Fix**: Ensure upstream link produces the required artifact:

```bash
# Check link contract
cat dawn/links/build.ci/link.yaml
```

### Link Exceeds Timeout

**Error**: `BUDGET_TIMEOUT: Link build.ci exceeded wall time limit`

**Fix**: Increase timeout in pipeline or policy:

```yaml
# In pipeline YAML
links:
  - id: build.ci
    config:
      max_wall_time_sec: 600
```

### Schema Validation Failed

**Error**: `SCHEMA_INVALID: quality.gates.report is not valid JSON`

**Fix**: Check link output format matches schema declaration.

---

## 10. Next Steps

- **Explore Links**: Browse `dawn/links/` to see available implementations
- **Read Weave Guide**: Consult [weave.md](weave.md) for pipeline composition patterns
- **Create Custom Links**: Use the link factory:
  ```bash
  python3 -m dawn.factory.generate_link <new_link_id>
  ```
- **Review Policy**: Customize `dawn/policy/runtime_policy.yaml` for your needs
- **Consult SRS**: Read [srs.md](srs.md) for system architecture details

---

## Quick Reference Card

| Task | Command |
|------|---------|
| Run pipeline | `python3 -m dawn.runtime.main --project <id> --pipeline <yaml>` |
| View summary | `python3 -m dawn.runtime.summary projects/<id>/ledger/events.jsonl` |
| List links | `python3 -c "from dawn.runtime.registry import Registry; r = Registry('dawn/links'); r.discover_links(); print(list(r.links.keys()))"` |
| Create project | `python3 -m dawn.runtime.new <project_id>` |
| Strict mode | `export DAWN_STRICT_ARTIFACT_ID=1` |
| Isolation mode | `--profile isolation` |
| View artifacts | `ls -R projects/<id>/artifacts/` |
| View ledger | `tail projects/<id>/ledger/events.jsonl` |

---

**Ready to dive deeper?** Check out:
- [INSTALL.md](INSTALL.md) - Complete installation guide
- [weave.md](weave.md) - Pipeline composition patterns
- [product.yaml](product.yaml) - Product capabilities reference
