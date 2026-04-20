# ForgeScaffold app_mvp Examples (Phase 2)

## Commands used

```bash
python3 -m dawn.runtime.main --project app_mvp --pipeline dawn/pipelines/forgescaffold_blueprint_v2.yaml
python3 scripts/verify_forgescaffold_phase2.py --project app_mvp
```

## What changed from Phase 1 → Phase 2

- Added a unified log envelope schema (`log_envelope.schema.json`).
- Generated an instrumentation patchset (`instrumentation.patchset.json`) that adds a minimal logger wrapper and entrypoint logging stubs.
- Added a runnable test harness (`test_harness/`) and updated test commands in the matrix to reference it.

## Known limitations (Phase 2)

- Dataflow edge discovery is still heuristic and minimal (Phase 2 focuses on scaffolding, not full analysis).
- Instrumentation patchset is generate-only; it does not apply changes by default.
- Language detection prioritizes Python/Node and may miss polyglot projects.

## Artifact overview

- `log_envelope.schema.json`: Portable logging schema for modules/services/agent steps.
- `instrumentation.patchset.json`: Deterministic patchset describing minimal observability changes.
- `test_harness/`: Runnable L0 harness stub(s) and manifest.
