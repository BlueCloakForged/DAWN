# DAWN Installation Guide

**DAWN (Deterministic Auditable Workflow Network)** - ForgeChain v0.10.3

A controlled execution environment for deterministic pipelines with audit-ready evidence and contract enforcement.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [System Requirements](#system-requirements)
- [Installation](#installation)
- [Post-Installation Verification](#post-installation-verification)
- [Configuration](#configuration)
- [Optional Components](#optional-components)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required Software

1. **Python 3.8 or higher**
   ```bash
   # Check your Python version
   python3 --version
   ```

2. **pip** (Python package installer)
   ```bash
   # Verify pip is installed
   pip3 --version
   ```

3. **Git** (for cloning the repository)
   ```bash
   # Verify git is installed
   git --version
   ```

### System-Specific Dependencies

#### macOS (via Homebrew)

```bash
# Install Homebrew if not already installed
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install system dependencies (required for T2T integration)
brew install tesseract poppler
```

#### Linux (Debian/Ubuntu)

```bash
# Update package list
sudo apt update

# Install system dependencies (required for T2T integration)
sudo apt install -y tesseract-ocr poppler-utils python3-dev
```

#### Windows

1. **Tesseract OCR**: Download and install from [UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/wiki)
   - Add Tesseract to your PATH environment variable

2. **Poppler**: Download from [poppler-windows](https://blog.alivate.com.au/poppler-windows/)
   - Extract and add `bin/` directory to your PATH

---

## System Requirements

### Minimum Requirements

- **CPU**: 2+ cores
- **RAM**: 4 GB minimum, 8 GB recommended
- **Disk Space**: 2 GB for installation, additional space for project artifacts
- **OS**: macOS 10.14+, Linux (Ubuntu 20.04+, Debian 10+), Windows 10+

### Recommended for Production

- **CPU**: 4+ cores
- **RAM**: 16 GB
- **Disk Space**: 10+ GB with SSD storage
- **Python**: 3.10+ for best performance

---

## Installation

### Step 1: Clone the Repository

```bash
# Clone the DAWN repository
cd ~
git clone <repository-url> DAWN
cd DAWN
```

### Step 2: Create a Virtual Environment

**Highly recommended** to avoid dependency conflicts:

```bash
# Create virtual environment
python3 -m venv .venv

# Activate the virtual environment
# macOS/Linux:
source .venv/bin/activate

# Windows (PowerShell):
.venv\Scripts\Activate.ps1

# Windows (Command Prompt):
.venv\Scripts\activate.bat
```

You should see `(.venv)` prefix in your terminal prompt when activated.

### Step 3: Install Python Dependencies

```bash
# Upgrade pip to latest version
pip install --upgrade pip

# Install core DAWN dependencies
pip install -r requirements.txt
```

**Note**: If you encounter errors with specific packages (e.g., `opencv-python` or `pymupdf`), you may need to install platform-specific build tools:

- **macOS**: `xcode-select --install`
- **Linux**: `sudo apt install build-essential python3-dev`
- **Windows**: Install [Visual Studio Build Tools](https://visualstudio.microsoft.com/downloads/)

### Step 4: Verify Installation

```bash
# Test DAWN runtime import
python3 -c "from dawn.runtime.orchestrator import Orchestrator; print('✅ DAWN runtime loaded successfully')"

# Check installed packages
pip list | grep -E "(PyYAML|filelock|jsonschema|psutil)"
```

---

## Post-Installation Verification

### Run Built-in Tests

```bash
# Verify Phase 3 functionality
python3 scripts/verify_phase3.py

# Verify Phase 6 functionality
python3 scripts/verify_phase6.py
```

### Test Pipeline Execution

```bash
# Create a test project
python3 -m dawn.runtime.main --project test_install --pipeline dawn/pipelines/basic.yaml

# Check for successful execution
ls -la projects/test_install/
```

Expected output should include:
- `artifacts/` directory
- `ledger/` directory with event logs
- `artifact_index.json`
- `pipeline.yaml`

---

## Configuration

### Environment Variables

Create a `.env` file in the project root (optional):

```bash
# Strict artifact ID enforcement (recommended for production)
export DAWN_STRICT_ARTIFACT_ID=1

# Set default isolation profile
export DAWN_DEFAULT_PROFILE=normal  # or 'isolation'

# Enable debug logging
export DAWN_DEBUG=1
```

### Policy Configuration

Edit `dawn/policy/runtime_policy.yaml` to customize:

- Resource budgets (project size, link timeouts, output size limits)
- Isolation profiles (normal vs. isolation mode)
- Security settings (allowed src/ writes, artifact-only outputs)

Example:

```yaml
# dawn/policy/runtime_policy.yaml
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

## Optional Components

### T2T Agent (Text-to-Topology)

The T2T agent provides a web interface for document processing and network topology generation.

#### Installation

T2T dependencies are already included in `requirements.txt`. To run the T2T agent:

```bash
cd T2T
streamlit run app.py
```

Access the web interface at `http://localhost:8501`

#### System Dependencies Required

- **Tesseract OCR**: For text extraction from images
- **Poppler**: For PDF rendering

### ForgeChain Console (Agent API Server)

A JSON API server for programmatic agent interaction.

```bash
cd forgechain_console
python3 server.py
```

---

## Troubleshooting

### Common Issues

#### 1. **Import Error: `filelock` not found**

```bash
pip install filelock
```

#### 2. **Policy Validation Failed**

```bash
# Verify policy file syntax
python3 -c "from dawn.policy import get_policy_loader; get_policy_loader()"
```

If errors persist, check `dawn/policy/runtime_policy.yaml` for YAML syntax errors.

#### 3. **psutil Installation Fails**

`psutil` is optional. If installation fails:

```bash
# Remove psutil from requirements.txt or install platform-specific wheels
pip install psutil --only-binary :all:
```

Without `psutil`, resource metrics will show as "unavailable" but DAWN will still function.

#### 4. **Tesseract/Poppler Not Found (T2T)**

```bash
# macOS: Verify installation
which tesseract
which pdfinfo

# Add to PATH if needed
export PATH="/usr/local/bin:$PATH"

# Linux: Reinstall
sudo apt install --reinstall tesseract-ocr poppler-utils
```

#### 5. **Permission Denied on Project Lock**

```bash
# Clean up stale lock files
rm projects/*/.lock

# Ensure proper file permissions
chmod -R u+rw projects/
```

#### 6. **Link Not Found in Registry**

```bash
# Force registry refresh
python3 -c "from dawn.runtime.registry import Registry; r = Registry('dawn/links'); r.discover_links(); print(f'Found {len(r.links)} links')"
```

### Getting Help

- Check `ledger/` directory for detailed error logs
- Review `artifact_index.json` for artifact resolution issues
- Enable debug mode: `export DAWN_DEBUG=1`
- Examine pipeline execution with `--profile isolation` for stricter enforcement

### Logging

DAWN logs execution events to:
- `projects/<project_id>/ledger/*.json` - Event ledger entries
- `projects/<project_id>/artifacts/dawn.metrics.run_summary/run_summary.json` - Pipeline summaries

---

## Next Steps

Once installation is complete:

1. **Read the [Quick Start Guide](QUICKSTART.md)** for usage examples
2. **Explore example pipelines** in `dawn/pipelines/`
3. **Review link contracts** in `dawn/links/`
4. **Consult the [Product Specification](product.yaml)** for capabilities and configuration

---

## Upgrading

To upgrade DAWN to the latest version:

```bash
# Pull latest changes
git pull origin main

# Update dependencies
pip install --upgrade -r requirements.txt

# Verify installation
python3 scripts/verify_phase6.py
```

---

**Questions or Issues?**

- Check the [Troubleshooting](#troubleshooting) section
- Review system logs in `ledger/` directories
- Consult `srs.md` for system architecture details
