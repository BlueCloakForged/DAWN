# Diagnostic Pipeline System Implementation

Build a dedicated diagnostic pipeline to capture and query terminal-style logs, separate from the main KùzuDB/LanceDB stores.

## Proposed Changes

### 1. Diagnostic Logger [NEW]
- **File**: `utils/diagnostic_logger.py`
- **Logic**: 
    - Implement `DiagnosticLogger` class using SQLite.
    - Schema: `logs (id, timestamp, level, component, message, metadata)`.
    - Provide a way to capture `stdout` and `stderr` or act as a standard logging handler.

### 2. System Integration [MODIFY]
- **File**: `start_sam_full.py`
- **Logic**:
    - Initialize `DiagnosticLogger` on startup.
    - Redirect subprocess outputs (like sandbox) to the diagnostic log.
    - Optionally patch `sys.stdout`/`sys.stderr` to capture main process output.

### 3. Query Utility [NEW]
- **File**: `scripts/query_diagnostic_logs.py`
- **Logic**:
    - CLI tool to search the SQLite database.
    - Support for keyword filtering (`Error`, `failure`).
    - Support for time-based filtering.

### 4. WebUI Interaction Tracking [NEW]
- **File**: `utils/diagnostic_logger.py`
- **Logic**:
    - Add `log_ui_event(action, label, metadata)` method to `DiagnosticLogger`.
    - Level: `UI`, Component: `WEBUI`.
- **Integration**:
    - Update `ui/dream_canvas.py`, `ui/bulk_ingestion_ui.py`, and `ui/insight_archive_ui.py` to log button clicks.
    - Capture context like cluster IDs, research modes, and export formats.

### 6. Automated Error Hooking [NEW]
- **File**: `secure_streamlit_app.py`
- **Logic**: 
    - Implement a decorator or wrapper for Streamlit `main()` or individual page renderers.
    - Block: `try: ... except Exception as e: diag_logger.log(traceback.format_exc(), level="ERROR", component="WEBUI_CRASH")`.
    - Ensure errors that usually only appear in the terminal are now visible in `query_diagnostic_logs.py`.

### 7. Page Expansion (High-Traffic) [NEW]
- **Files**: `ui/chat_ui.py`, `ui/autonomy_dashboard.py`, `ui/memory_app.py`.
- **Instrumentation**:
    - Chat: Log message sends, tool calls, and clear-chat actions.
    - Autonomy: Log agent activation, policy toggles, and manual overrides.
    - Memory: Log deletions, batch operations, and search queries.

## Verification Plan

### Automated Tests
- Script to generate mock logs and verify they are stored in the database.
- Script to run queries against mock data and verify expected results.
- **Stress Test**: `scripts/stress_test_diagnostics.py` to verify SQLite concurrency handling.

### Manual Verification
- Start SAM via `start_sam_full.py` and check if `logs/diagnostic_logs.db` is created.
- Run `scripts/query_diagnostic_logs.py` to see captured startup logs.
- **Error Capture**: Intentionally trigger a Python error in a UI component and verify the traceback is captured.
