# Validation & Diagnostic Framework Template

This folder contains a template version of the diagnostic pipeline developed for the SAM project. You can use these files to implement consistent logging, background error monitoring, and diagnostic querying in other applications.

## Folder Structure

### 📁 `code/`
- **`diagnostic_logger.py`**: The core engine. It manages a dedicated SQLite database (`logs/diagnostic_logs.db`) for system health and UI events.
- **`error_sentry.py`**: A background monitoring script that polls the diagnostic database for novel errors and saves them as markdown reports in `FoundErrors/`.
- **`query_diagnostic_logs.py`**: A CLI utility for searching and filtering the diagnostic database.
- **`stress_test_diagnostics.py`**: A multi-threaded stress test to verify SQLite concurrency and lock handling.

### 📁 `docs/`
- **`template_implementation_plan.md`**: A structured blueprint for rolling out a diagnostic framework. Use this to plan your integration.
- **`template_walkthrough.md`**: A summary of work accomplished and verified. Useful for documenting your progress.
- **`template_task.md`**: A task-list template to track milestones.

## How to use
1. **Integrate the Logger**: Place `diagnostic_logger.py` in your `utils/` folder and call `get_diagnostic_logger().log(...)` in your application.
2. **Handle Locks**: Ensure you use the `timeout=30.0` parameter in your SQLite connections as shown in the template code.
3. **Run the Sentry**: Start `error_sentry.py` in a separate terminal or background process to get alerted on new bugs.
