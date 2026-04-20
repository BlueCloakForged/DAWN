# ForgeScaffold CLI Reference (v1.0)

## Commands (one-line purpose)
- status: Show project operational status (lock, integrity, cache, recent runs).
- apply: Run ForgeScaffold apply pipeline with preflight + guided HITL handling.
- approve: Record an approval receipt from an approval template.
- query: Query evidence index (cache preferred, JSONL fallback).
- explain: Explain why a run was blocked/failed and print exact next steps.
- doctor: Preflight diagnostics (policy, write roots, lock, integrity, cache).

## Required flags by command
- status: `--project`
- apply: `--project`
- approve: `--project` + `--approval` + `--approver` + `--reason`
- query: `--project`
- explain: `--project` + (`--last` or `--error-code`)
- doctor: `--project`

## --json contract
- `--json` prints the exact JSON artifact to stdout.
- Human output is suppressed when `--json` is used.
- JSON artifacts are written under `projects/<project>/artifacts/forgescaffold.cli/` unless `--out` is provided.

## Exit codes
- 0: SUCCESS (PASS or expected WARN in runnable_only)
- 10: SUCCESS_WITH_WARN (runnable_only WARN)
- 20: USER_INPUT_ERROR
- 30: POLICY_BLOCKED (e.g., TICKET_REQUIRED, HIGH_RISK_BLOCKED)
- 31: APPROVAL_REQUIRED / APPROVAL_INVALID
- 32: LOCK_HELD / LOCK_INVALID
- 40: PIPELINE_FAILED
- 50: INTEGRITY_FAILED
- 60: INTERNAL_ERROR

## Pipeline selection rules
- `--pipeline` overrides all defaults.
- If not provided, pipeline is derived from policy default mode:
  - strict -> `dawn/pipelines/forgescaffold_apply_v9_cache.yaml`
  - runnable_only -> `dawn/pipelines/forgescaffold_apply_v9_cache_runnable.yaml`

## Golden examples
- status:
  `python3 scripts/forgescaffold_cli.py status --project app_mvp`
- apply (runnable_only):
  `python3 scripts/forgescaffold_cli.py apply --project app_mvp --mode runnable_only --yes`
- approve:
  `python3 scripts/forgescaffold_cli.py approve --project app_mvp --approval <template_path> --approver "Ada" --reason "reviewed" --yes`
- query:
  `python3 scripts/forgescaffold_cli.py query --project app_mvp --limit 5`
- explain:
  `python3 scripts/forgescaffold_cli.py explain --project app_mvp --last`
- doctor:
  `python3 scripts/forgescaffold_cli.py doctor --project app_mvp --mode runnable_only`
