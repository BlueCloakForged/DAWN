# Validation Framework Template (Self-Healing Engine)

This is a portable, modular system for error monitoring and autonomous repair ("Self-Healing"). It is designed to be dropped into any AI-driven application to provide robust diagnostics, automated restoration, and status tracking.

## Directory Structure

```text
validation_framework_template/
├── core/
│   ├── logger.py       # Universal Logger (SQLite-backed with Status Tracking)
│   ├── sentry.py       # Background error monitor with resource guardrails
│   └── engine.py       # LADDER Repair Engine (Logic, Action, Data...)
├── config/             # Config files for the host application
└── patterns/           # Registry of fix patterns (Regex -> Action)
    └── system_fixes.json
```

## Quick Start

### 1. Integration (Logging)
In your application's main entry point:
```python
from validation_framework_template.core.logger import setup_logging
logger = setup_logging(db_path="logs/app_diagnostics.db", app_name="MY_APP")

# Log an error
logger.error("Something went wrong!", component="AUTH")
```

### 2. Autonomous Sentry
To enable background monitoring and auto-fix:
```python
from validation_framework_template.core.sentry import Sentry
from validation_framework_template.core.engine import RepairEngine

# Initialize engine and sentry
engine = RepairEngine(logger, patterns_path="validation_framework_template/patterns/system_fixes.json")
sentry = Sentry(db_path="logs/app_diagnostics.db", repair_callback=engine.diagnose_and_fix)
sentry.start()
```

### 3. Adding Fix Patterns
Add regex-based patterns to `patterns/system_fixes.json`:
```json
{
    "patterns": [
        {
            "name": "Config Reset",
            "message_contains": "invalid configuration",
            "action_type": "command",
            "action_payload": "cp config_default.json config.json && echo 'Config Reset Applied'"
        }
    ]
}
```

## CLI Management Tool
You can create a CLI tool (similar to `scripts/sam_repair_tool.py`) to manage errors:

### List Unresolved Errors
```bash
python3 scripts/sam_repair_tool.py --list --status unresolved
```

### Manually Repair an Error
```bash
python3 scripts/sam_repair_tool.py --auto-repair <ID>
```

### Run Auto-Pilot (Batch Resolve)
Resolve all outstanding errors in chronological order:
```bash
python3 scripts/sam_repair_tool.py --auto-pilot
```

## Features
- **Repair Status Tracking**: Automatically marks errors as `UNRESOLVED`, `REPAIRED`, or `FAILED`.
- **Auto-Pilot Mode**: Bulk-processes the entire error backlog autonomously.
- **LADDER compliant**: Supports Logic, Action, Data, Diagnosis, Execution, and Recovery cycles.
- **Resource Guardrails**: Automatically aborts repairs if system memory or CPU usage is too high.
- **Sequential Safety**: Processes repairs one-by-one to prevent cascading system load.
- **SQLite Backed**: High-performance, concurrent-safe logging with zero external dependencies.
