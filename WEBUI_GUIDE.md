# DAWN Operator Console - WebUI Getting Started Guide

**Quick guide to start and use the DAWN Operator Console web interface**

---

## Quick Start Command

```bash
# From the DAWN root directory
cd forgechain_console && python3 server.py
```

**Access at**: http://localhost:3434

---

## Prerequisites

1. **Completed installation** (see [INSTALL.md](INSTALL.md))
2. **Virtual environment activated**:
   ```bash
   source .venv/bin/activate
   ```
3. **FastAPI dependencies installed** (included in requirements.txt)

---

## Step-by-Step Startup

### 1. Navigate to Console Directory

```bash
cd ~/DAWN/forgechain_console
```

### 2. Activate Virtual Environment (if not already active)

```bash
source ../venv/bin/activate
```

### 3. Start the Server

```bash
python3 server.py
```

**Expected output**:
```
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:3434
```

### 4. Open Browser

Navigate to: **http://localhost:3434**

---

## WebUI Features

### 📋 Project Dashboard

**View all projects** with status indicators:
- List active and completed projects
- See last execution status (SUCCEEDED/FAILED/RUNNING)
- Quick access to project details

### ➕ Create New Project

1. Click **"New Project"** button
2. Enter **Project ID** (e.g., `my_app`)
3. Select **Pipeline** (e.g., `default_app_dev`)
4. Choose **Profile** (`normal` or `isolation`)
5. Click **"Create"**

### ▶️ Run Pipeline

1. Select a project from the list
2. Click **"Run Pipeline"**
3. Choose configuration:
   - **Pipeline ID** (optional override)
   - **Profile** (`normal` or `isolation`)
   - **Executor** (`local`, `subprocess`, or `queue`)
4. Click **"Execute"**

### 📊 Monitor Execution

**Live execution monitoring includes**:
- ✅ Real-time status updates (RUNNING → SUCCEEDED/FAILED)
- 📟 **Terminal overlay**: Live log streaming
- ⏱️ Execution timing and progress
- 🔄 Auto-refresh when pipeline completes

### 📦 View Artifacts

After pipeline execution:
1. Navigate to project detail page
2. Click **"Artifacts"** tab
3. **Preview** text/JSON artifacts inline
4. **Download** individual artifacts or full bundles

### ✅ Approve Gates

For gates requiring human approval:
1. Pipeline pauses at gate (e.g., `gate.human_review`)
2. WebUI shows **"Approval Required"** notification
3. Review the request details
4. Click **"Approve"** or **"Reject"**
5. Optionally add reason/notes
6. Pipeline continues automatically

### 📝 Edit Project Inputs

1. Go to project detail page
2. Click **"Inputs"** tab
3. Select file to edit (e.g., `idea.md`, `requirements.json`)
4. Make changes in the editor
5. Click **"Save"**

**Allowed file types**: `.md`, `.json`, `.yaml`, `.yml`, `.txt`

### 📈 View Audit Report

1. Navigate to project detail
2. Click **"View Report"** button
3. See comprehensive project report including:
   - Dependency graph
   - Link execution timeline
   - Budget diagnostics
   - Retry history
   - Policy compliance

### 📜 Run History

1. Go to project detail page
2. Click **"Run History"** tab
3. Browse previous executions
4. Click any run to see:
   - Execution logs
   - Artifacts produced
   - Performance metrics
   - Error details (if failed)

---

## Common Workflows

### Workflow 1: Create and Run a New Project

```bash
# 1. Start the WebUI
cd ~/DAWN/forgechain_console && python3 server.py

# 2. In browser (http://localhost:3434):
#    - Click "New Project"
#    - Project ID: demo_app
#    - Pipeline: default_app_dev
#    - Profile: normal
#    - Click "Create"

# 3. Run the pipeline:
#    - Click "Run Pipeline"
#    - Click "Execute"

# 4. Watch logs in Terminal overlay

# 5. View artifacts when complete
```

### Workflow 2: Approve a Human Review Gate

```bash
# 1. Run pipeline with gate.human_review
# 2. Pipeline pauses, UI shows notification
# 3. Click "Review Request"
# 4. Read the details
# 5. Click "Approve" with optional reason
# 6. Pipeline resumes automatically
```

### Workflow 3: Download Evidence Bundle

```bash
# 1. Navigate to completed project
# 2. Click "Downloads" tab
# 3. Click "Evidence Pack" or "Release Bundle"
# 4. ZIP file downloads with all artifacts + audit trail
```

---

## API Endpoints

The console also exposes REST API endpoints for programmatic access:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/pipelines` | GET | List available pipelines |
| `/api/projects` | GET | List all projects |
| `/api/projects` | POST | Create new project |
| `/api/projects/{id}` | GET | Get project details |
| `/api/projects/{id}/run` | POST | Execute pipeline |
| `/api/projects/{id}/runs` | GET | List run history |
| `/api/projects/{id}/artifacts` | GET | List artifacts |
| `/api/projects/{id}/inputs` | GET | List input files |
| `/api/projects/{id}/gate` | POST | Resolve gate approval |
| `/api/projects/{id}/report` | GET | Get project report |

---

## Troubleshooting

### Port Already in Use

```bash
# Error: Address already in use
# Solution: Kill existing process or change port

# Find process on port 3434
lsof -ti:3434

# Kill the process
kill $(lsof -ti:3434)

# Or change port in server.py (line 34):
# PORT = 3435
```

### WebUI Won't Load

```bash
# 1. Verify server is running
ps aux | grep "python3 server.py"

# 2. Check for errors in terminal
# Look for import errors or module not found

# 3. Reinstall dependencies
pip install fastapi uvicorn sse-starlette pydantic
```

### "Project Not Found" Error

```bash
# The project_index.json is missing or invalid
# Solution: Run the pipeline via CLI first to generate index

python3 -m dawn.runtime.main \
  --project my_project \
  --pipeline dawn/pipelines/default.yaml
```

### Artifacts Not Showing

```bash
# Check if project_index.json exists and is valid
cat projects/my_project/project_index.json | jq .

# Verify artifacts exist on disk
ls -la projects/my_project/artifacts/
```

---

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl + R` | Refresh project list |
| `Esc` | Close modal/overlay |

---

## Configuration

### Change Server Port

Edit `forgechain_console/server.py` line 34:

```python
PORT = 3434  # Change to desired port
```

### Enable CORS (for external access)

Add to `server.py` after line 24:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## Security Notes

- **Local access only**: Server binds to `127.0.0.1` by default
- **No authentication**: Designed for local development use
- **File editing restricted**: Only specific file types allowed
- **Path validation**: Prevents directory traversal attacks

For production deployment, add:
- Authentication middleware
- HTTPS/TLS
- Rate limiting
- Input validation

---

## Next Steps

- **Explore links**: Browse available links at `dawn/links/`
- **Create custom pipelines**: See [weave.md](weave.md) for composition patterns
- **Configure policies**: Edit `dawn/policy/runtime_policy.yaml`
- **CLI usage**: Refer to [QUICKSTART.md](QUICKSTART.md) for command-line operations

---

## Summary

**To start DAWN WebUI**:
```bash
cd forgechain_console && python3 server.py
```

**Then open**: http://localhost:3434

You now have a full-featured operator console for managing DAWN pipelines with live monitoring, artifact browsing, gate approvals, and audit reporting!
