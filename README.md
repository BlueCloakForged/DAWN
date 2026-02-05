# DAWN - Deterministic Auditable Workflow Network

**ForgeChain v0.10.3** - A controlled execution environment for deterministic pipelines with audit-ready evidence and contract enforcement.

---

## 🚀 Quick Start

### Start the WebUI (Operator Console)

```bash
cd forgechain_console && python3 server.py
```

**Access at**: http://localhost:3434

### Or Use the CLI

```bash
python3 -m dawn.runtime.main --project my_app --pipeline dawn/pipelines/default.yaml
```

---

## 📚 Documentation

| Guide | Purpose |
|-------|---------|
| **[WEBUI_GUIDE.md](WEBUI_GUIDE.md)** | Start and use the web-based Operator Console |
| **[QUICKSTART.md](QUICKSTART.md)** | CLI quick start with examples and commands |
| **[INSTALL.md](INSTALL.md)** | Complete installation guide with troubleshooting |
| **[requirements.txt](requirements.txt)** | All Python dependencies |

---

## 💡 What is DAWN?

DAWN executes **deterministic pipelines** composed of **links** (autonomous units of work):

- **Links**: Self-contained tasks with explicit `requires`/`produces` contracts
- **Pipelines**: Ordered chains of links defined in YAML
- **Artifacts**: Versioned outputs tracked in an artifact index
- **Ledger**: Immutable audit trail of all execution events

---

## ✨ Key Features

### Operator Console WebUI
- 📋 Project management and creation
- ▶️ Pipeline execution with live monitoring
- 📊 Real-time log streaming
- 📦 Artifact browsing and download
- ✅ Inline gate approvals
- 📈 Audit reports and dashboards

### Deterministic Execution
- Contract enforcement (requires/produces)
- Strict artifact IDs for unambiguous dependencies
- Schema validation for JSON artifacts
- Idempotent execution with input signatures

### Audit & Compliance
- Immutable ledger of all events
- Resource budgets (time, size, CPU)
- Sandbox enforcement (writes only to allowed paths)
- Evidence packs for compliance reporting

### Flexibility
- Multiple executors (local, subprocess, queue)
- Isolation profiles (normal vs. strict isolation)
- Conditional execution (`on_success`, `on_failure`)
- Policy-driven configuration

---

## 🏗️ Architecture

```
DAWN/
├── dawn/
│   ├── runtime/          # Core orchestration engine
│   ├── links/            # Catalog of executable links
│   ├── pipelines/        # Pipeline definitions (YAML)
│   ├── policy/           # Runtime policies and budgets
│   └── factory/          # Link scaffolding tools
├── forgechain_console/   # WebUI Operator Console
│   ├── server.py         # FastAPI backend
│   └── static/           # Web UI files
├── T2T/                  # Text-to-Topology agent
├── projects/             # Project workspaces
└── docs/                 # Additional documentation
```

---

## 🎯 Common Use Cases

### Software Development Lifecycle
```yaml
links:
  - service.catalog      # Generate service catalog
  - build.ci             # Build and test
  - quality.gates        # Run quality checks
  - package.evidence_pack # Create audit bundle
```

### Infrastructure as Code
```yaml
links:
  - validation.terraform  # Validate TF configs
  - impl.apply_changes    # Apply infrastructure
  - validation.compliance # Compliance checks
```

### Change Control
```yaml
links:
  - impl.generate_patchset  # Generate changes
  - gate.patch_approval     # Require approval
  - impl.apply_patchset     # Apply changes
  - chain.validator         # Validate result
```

---

## 📦 Installation

### Quick Install

```bash
# Clone repository
git clone <repository-url> DAWN
cd DAWN

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install system dependencies (macOS)
brew install tesseract poppler

# Start WebUI
cd forgechain_console && python3 server.py
```

**Detailed instructions**: See [INSTALL.md](INSTALL.md)

---

## 🔧 Configuration

### Environment Variables

```bash
export DAWN_STRICT_ARTIFACT_ID=1  # Enforce strict artifact IDs
export DAWN_DEFAULT_PROFILE=normal # or 'isolation'
```

### Runtime Policy

Edit `dawn/policy/runtime_policy.yaml`:

```yaml
budgets:
  per_project:
    max_project_bytes: 500000000  # 500 MB
  per_link:
    max_output_bytes: 50000000    # 50 MB
    max_wall_time_sec: 300        # 5 minutes

profiles:
  normal:
    allow_src_writes: true
  isolation:
    allow_src_writes: false
    artifact_only_outputs: true
```

---

## 🧪 Testing

```bash
# Run verification scripts
python3 scripts/verify_phase3.py
python3 scripts/verify_phase6.py

# Test pipeline execution
python3 -m dawn.runtime.main \
  --project test_project \
  --pipeline dawn/pipelines/basic.yaml
```

---

## 📊 Example Workflow

### Using the WebUI

1. **Start console**: `cd forgechain_console && python3 server.py`
2. **Open browser**: http://localhost:3434
3. **Create project**: Click "New Project" → Enter details
4. **Run pipeline**: Select project → Click "Run Pipeline"
5. **Monitor**: Watch live logs in Terminal overlay
6. **View results**: Browse artifacts and audit report

### Using the CLI

```bash
# Create project
python3 -m dawn.runtime.new my_app

# Add source files
echo 'print("Hello DAWN")' > projects/my_app/src/main.py

# Run pipeline
python3 -m dawn.runtime.main \
  --project my_app \
  --pipeline dawn/pipelines/default.yaml

# View summary
python3 -m dawn.runtime.summary projects/my_app/ledger/events.jsonl
```

---

## 🛠️ Creating Custom Links

```bash
# Use the link factory
python3 -m dawn.factory.generate_link my_custom_link

# Edit the generated files
# - dawn/links/my_custom_link/link.yaml  (contract)
# - dawn/links/my_custom_link/run.py     (implementation)

# Use in pipeline
# - Add to pipelines/my_pipeline.yaml
```

---

## 🤝 Components

### Core Runtime
- **Orchestrator**: Pipeline execution engine
- **Registry**: Link discovery and metadata
- **Ledger**: Event logging and audit trail
- **Artifact Store**: Artifact tracking and digests

### Operator Console (WebUI)
- **FastAPI backend**: REST API + SSE streaming
- **Static frontend**: HTML/CSS/JS interface
- **Real-time updates**: Live log streaming
- **Index-driven**: Uses `project_index.json` as source of truth

### T2T Agent
- **Document processing**: PDF/DOCX parsing
- **Topology extraction**: Network diagram analysis
- **Streamlit UI**: Interactive web interface

---

## 📖 Additional Resources

- **[product.yaml](product.yaml)** - Product specification and capabilities
- **[srs.md](srs.md)** - System requirements specification
- **[weave.md](weave.md)** - Pipeline composition patterns
- **[link.md](link.md)** - Link architecture diagram

---

## 🐛 Troubleshooting

### WebUI won't start
```bash
# Install missing dependencies
pip install fastapi uvicorn sse-starlette pydantic

# Check for port conflicts
lsof -ti:3434
```

### Pipeline fails with missing artifact
```bash
# Check artifact index
cat projects/my_project/artifact_index.json | jq .

# View ledger for errors
tail -n 50 projects/my_project/ledger/events.jsonl
```

**Full troubleshooting**: See [INSTALL.md](INSTALL.md#troubleshooting)

---

## 📝 License

[Your license here]

---

## 🙏 Support

- **Documentation**: See guides above
- **Issues**: Check ledger files for detailed errors
- **Debug mode**: `export DAWN_DEBUG=1`

---

**Ready to start?** Choose your interface:
- **WebUI**: See [WEBUI_GUIDE.md](WEBUI_GUIDE.md)
- **CLI**: See [QUICKSTART.md](QUICKSTART.md)
- **Installation**: See [INSTALL.md](INSTALL.md)
