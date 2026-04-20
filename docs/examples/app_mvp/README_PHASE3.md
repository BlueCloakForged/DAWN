# ForgeScaffold app_mvp Examples (Phase 3)

## Commands used

```bash
python3 -m dawn.runtime.main --project app_mvp --pipeline dawn/pipelines/forgescaffold_blueprint_v2.yaml
python3 scripts/verify_forgescaffold_phase2.py --project app_mvp
python3 -m dawn.runtime.main --project app_mvp --pipeline dawn/pipelines/forgescaffold_apply_v1.yaml --profile forgescaffold_apply_lowrisk
python3 -m dawn.runtime.main --project app_mvp --pipeline dawn/pipelines/forgescaffold_apply_v1_runnable.yaml --profile forgescaffold_apply_lowrisk
```

## Idempotent apply behavior (status=SKIPPED)

The apply link is idempotent for full-file operations:

- For add/modify operations, it computes the current file sha256 and compares it to the patchset `content_sha256`.
- If they match, the operation is skipped and reported as `SKIPPED_*`.
- If they differ, the operation proceeds (or fails if blocked by policy or drift).

This run produced `status=SKIPPED` because the logger file already existed with matching content.

## Verification status (WARN)

The strict pipeline uses `forgescaffold_apply_v1.yaml` (verify mode: strict). In app_mvp it may FAIL or WARN depending on environment deps.

The runnable pipeline uses `forgescaffold_apply_v1_runnable.yaml` (verify mode: runnable_only) and reports `WARN` because some commands are skipped due to missing dependencies in app_mvp:

- `grpc`, `pinecone`, `vectorstore` (Python imports)
- `pytest` (test runner for L0/L1 commands)

This is not a pipeline failure; it indicates runnable-only mode reported missing deps and continued.

## How to make verification PASS in a real app

1) Add required deps to `projects/app_mvp/src/requirements.txt`.
2) Install them into the active environment:

```bash
python3 -m pip install -r projects/app_mvp/src/requirements.txt
```

3) Re-run the Phase 3 pipeline with strict mode (default) or runnable-only if you still want skip reporting.

## Phase 3 artifacts added

- `apply_report.json`
- `rollback_patchset.json`
- `verification_report.json`
- `evidence_manifest.json`
