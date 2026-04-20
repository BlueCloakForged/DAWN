# Diagnostic Pipeline System Walkthrough

I have implemented a dedicated diagnostic pipeline to capture and query terminal logs for SAM. This system is isolated from the main procedural and memory stores to ensure that system-level errors or diagnostic noise do not interfere with SAM's architectural knowledge.

## Changes Made

### 1. Diagnostic Datastore
- **[DiagnosticLogger](file:///Users/vinsoncornejo/Downloads/augment-projects/SAM/SmallAgentModel-main/utils/diagnostic_logger.py)**: A new SQLite-backed logging system that handles structured storage of terminal messages.
- **SQLite Database**: `logs/diagnostic_logs.db` is initialized on startup to store timestamps, log levels, components, and messages.

### 2. Startup Integration
- **[start_sam_full.py](file:///Users/vinsoncornejo/Downloads/augment-projects/SAM/SmallAgentModel-main/start_sam_full.py)**: 
    - Automatically initializes the diagnostic logger.
    - Captures milestones like Docker status and curiosity service startup.
    - Streams output from background services (like the sandbox) directly into the diagnostic database using a non-blocking thread.

### 3. WebUI Interaction Tracking
- **[log_ui_event](file:///Users/vinsoncornejo/Downloads/augment-projects/SAM/SmallAgentModel-main/utils/diagnostic_logger.py#L92-100)**: Added a dedicated method to log UI actions (button clicks) with metadata like cluster IDs or research modes.
- **Integrated Components**: Added event hooks to `dream_canvas.py`, `bulk_ingestion_ui.py`, and `insight_archive_ui.py`.

### 4. Correlation & Enhanced Querying
- **[query_diagnostic_logs.py](file:///Users/vinsoncornejo/Downloads/augment-projects/SAM/SmallAgentModel-main/scripts/query_diagnostic_logs.py)**: Now supports highlighting `UI` events (in cyan) and displaying JSON metadata with the `--show-metadata` flag. This allows developers to see exactly what UI action preceded a backend warning or error.

## Verification Results

I verified the systems using a dedicated [verification script](file:///Users/vinsoncornejo/Downloads/augment-projects/SAM/SmallAgentModel-main/scripts/verify_ui_correlation.py) which simulates a "Run Synthesis" click followed by backend processing and warnings.

| Test Case | Result |
|-----------|--------|
| Logger Initialization | ✅ PASSED |
| Subprocess Streaming | ✅ PASSED |
| UI Event Logging | ✅ PASSED |
| Metadata Capture | ✅ PASSED |
| UI/Terminal Correlation | ✅ PASSED |

### Phase 3: Error Surface & Stress Testing
In this phase, I transformed the diagnostic pipeline from a passive logger into a proactive error-hunting system.

#### 1. Automated Error Hooking
I wrapped the main entry point in [secure_streamlit_app.py](file:///Users/vinsoncornejo/Downloads/augment-projects/SAM/SmallAgentModel-main/secure_streamlit_app.py) with a global exception handler.
- **Benefit**: Any high-level Python crash (the "red boxes" in Streamlit) is now automatically captured with its full traceback in the `ERROR` level logs.
- **Traceability**: These are tagged with `component="WEBUI_CRASH"`.

#### 2. Expanded UI Instrumentation
I broadened coverage to include the highest-traffic components of the SAM system:
- **Chat UI**: Tracks message volume, tool-augmented reasoning starts, and memory command execution.
- **Autonomy Dashboard**: Logs emergency pause/resume actions, manual goal triggers, and planning starts.
- **Memory Control Center**: Captures navigations, data refreshes, and command-line interactions.

#### 3. Concurrency Stress Test
To ensure the system remains stable during high activity, I ran a concurrency stress test using [scripts/stress_test_diagnostics.py](file:///Users/vinsoncornejo/Downloads/augment-projects/SAM/SmallAgentModel-main/scripts/stress_test_diagnostics.py).
- **Result**: Successfully logged **500 concurrent events** from 10 workers at **~272 events/second**.

Captured logs can be queried with:
```bash
python scripts/query_diagnostic_logs.py --show-metadata
```

### Phase 4: Engine Stability and Deduplication
Focused on resolving business-critical UI failures and stale state issues.

#### 1. Deep Research Engine Synchronization
Successfully diagnosed and fixed the "Deep Research Engine not available" error that was occurring despite correctly installed modules.
- **Enhanced Hooks**: Instrumented [dream_canvas.py](file:///Users/vinsoncornejo/Downloads/augment-projects/SAM/SmallAgentModel-main/ui/dream_canvas.py) and [memory_app.py](file:///Users/vinsoncornejo/Downloads/augment-projects/SAM/SmallAgentModel-main/ui/memory_app.py) with detailed import tracebacks.
- **Diagnostic Signal**: Verified that critical engine modules now correctly route their health status to the `DiagnosticLogger`.

#### 2. Vetting Queue Deduplication Fix
Resolved a persistent issue where papers appeared twice in the "Analyzing..." section of the Vetting Queue.
- **The Bug**: Metadata construction in the Deep Research loop was missing the `arxiv_id` field, which caused the queue manager's deduplication logic to fail (since it relies on that ID).
- **The Fix**: Updated `ui/dream_canvas.py` to correctly include the `arxiv_id` in [paper_metadata](file:///Users/vinsoncornejo/Downloads/augment-projects/SAM/SmallAgentModel-main/ui/dream_canvas.py#L3926-L3932).
- **Cleanup**: Implemented [scripts/cleanup_vetting_queue.py](file:///Users/vinsoncornejo/Downloads/augment-projects/SAM/SmallAgentModel-main/scripts/cleanup_vetting_queue.py) which purged stale duplicate records from September 2025 that were cluttering the UI.

Captured research completion logs:
```bash
sqlite3 logs/diagnostic_logs.db "SELECT timestamp, component, message FROM diagnostic_log WHERE component='DEEP_RESEARCH' ORDER BY id DESC LIMIT 5;"
```

### Phase 5: Database Concurrency & Lock Mitigation
Resolved the "database is locked" errors occurring in the Insight Archive and Diagnostic Logger.

#### 1. SQLite Timeout Enhancement
Added a 30-second timeout to all critical SQLite connections to prevent immediate failures during concurrent operations.
- **Affected Components**: [insight_archive.py](file:///Users/vinsoncornejo/Downloads/augment-projects/SAM/SmallAgentModel-main/memory/synthesis/insight_archive.py), [diagnostic_logger.py](file:///Users/vinsoncornejo/Downloads/augment-projects/SAM/SmallAgentModel-main/utils/diagnostic_logger.py), and [error_sentry.py](file:///Users/vinsoncornejo/Downloads/augment-projects/SAM/SmallAgentModel-main/scripts/error_sentry.py).

#### 2. Batched Archival & UI Logic
Optimized the "Emergent Insights" load sequence to reduce database contention.
- **Batch Processing**: Implemented `archive_insights_batch()` in [insight_archive.py](file:///Users/vinsoncornejo/Downloads/augment-projects/SAM/SmallAgentModel-main/memory/synthesis/insight_archive.py) to process multiple insights in a single transaction.
- **Session Tracking**: Updated [insight_archive_ui.py](file:///Users/vinsoncornejo/Downloads/augment-projects/SAM/SmallAgentModel-main/ui/insight_archive_ui.py) to use batching and added `st.session_state.archived_synthesis_runs` to prevent redundant archival attempts during rapid Streamlit reruns.

#### 3. Concurrency Verification
Verified the stability of the fix using multi-threaded stress tests:
- **Insight Archive**: Successfully handled 50 concurrent writes across 5 threads with 0 failures.
- **Diagnostic Logger**: Successfully handled 200 concurrent writes across 10 threads with 0 failures.
